# 12. Consume frames in your own program

Write a program that links the driver and reads ADC frames as they complete. Without a radar it still builds and fails cleanly. Prerequisite: [tutorial 1](01_install.md).

## Install the driver and build a consumer

```bash
cmake --install CPSL_TI_Radar_cpp/build --prefix ~/cpsl_install
mkdir -p ~/radar_consumer && cd ~/radar_consumer
```

`CMakeLists.txt`:

```cmake
cmake_minimum_required(VERSION 3.11)
project(consumer CXX)
set(CMAKE_CXX_STANDARD 17)
find_package(CPSL_TI_Radar REQUIRED)
add_executable(consumer main.cpp)
target_link_libraries(consumer PRIVATE CPSL_TI_Radar::driver)
```

`main.cpp`:

```cpp
#include "Radar.hpp"

#include <complex>
#include <iostream>
#include <vector>

namespace radar = cpsl::radar;

int main(int argc, char** argv) {
    if (argc < 2) { std::cerr << "usage: consumer <system.json>\n"; return 2; }
    auto cfg = radar::RadarConfig::load(argv[1]);
    if (!cfg) { std::cerr << cfg.status.message << "\n"; return 1; }
    auto opened = radar::Radar::open(*cfg);        // opens ports and sockets; sends nothing
    if (!opened) { std::cerr << opened.status.message << "\n"; return 1; }
    radar::Radar& r = **opened;
    if (!r.configure() || !r.start()) return 1;    // cfg to the radar, then streaming

    radar::AdcFrame frame;                         // reused for every frame
    std::vector<std::complex<int16_t>> chirp0;     // what we keep: a copy
    radar::Status why;
    for (int n = 0; n < 100;) {
        if (!r.next_adc_frame(frame, std::chrono::milliseconds(1000), &why)) {
            if (why.code == radar::Code::timeout) continue;
            std::cerr << radar::to_string(why.code) << ": " << why.message << "\n";
            break;
        }
        n++;
        chirp0.clear();                            // frame.data[rx][sample][chirp]
        for (const auto& sample : frame.data[0]) chirp0.push_back(sample[0]);
        std::cout << "frame " << frame.index << ": " << chirp0.size() << " samples\n";
    }
    std::cout << "frames_overwritten=" << r.stats().frames_overwritten << "\n";
    return r.stop() ? 0 : 1;
}
```

```bash
cmake -S . -B build -DCMAKE_PREFIX_PATH=~/cpsl_install && cmake --build build
./build/consumer /nonexistent.json        # prints "cannot open system config", exits 1
./build/consumer ~/path/to/CPSL_TI_Radar/CPSL_TI_Radar_cpp/config/system/IWR1843_demo_stress_test_front.json
```

Use a DCA1000 config for the last line. For a serial config call `next_point_cloud(cloud, timeout, &why)` the same way; `cloud.points` is a `std::vector<Point>` (`x, y, z, v, snr_db, noise_db`).

## The swap contract

```
 driver pool:  [buf A] [buf B] [buf C] ...        your frame.data = [buf X]

 next_adc_frame(frame):   queue's oldest buffer  <-- swapped -->  frame.data
                          (A comes to you)                        (X goes back to the pool)
```

`next_adc_frame` does not copy. It **swaps** the oldest queued buffer into `frame.data` and the buffer you held goes back to the driver's pool. Consequences:

- Reuse one `AdcFrame` and nothing is allocated per frame.
- **Anything you point into `frame.data` is invalid after the next `next_adc_frame` call**, because that buffer now belongs to the driver. Copy what you keep, as `chirp0` does. (`next_point_cloud` swaps `cloud.points` the same way.)
- Frames come out in order, once each; `frame.missing_bytes` > 0 means lost packets were zero-filled.

## Queue depth and latency

Completed frames wait in a queue of `runtime.frame_queue_depth` frames (default 4). If your loop falls behind, the **oldest** frame is dropped and `Stats::frames_overwritten` counts it (`overwritten=` in `--stats`).

Depth 1 always gives you the newest frame and skips the rest when you are slow: lowest latency, lossy. A larger depth absorbs a stall of up to depth-1 frames without loss, but after a stall you read older frames, up to depth x frame period behind, until you catch up.

The serial stream differs: only the newest TLV frame waits (`serial_overwritten`). To keep up, do slow work (FFTs, disk) on another thread and pass it copies. `stop()` from another thread wakes a waiting `next_adc_frame` at once (`Code::stopped`).
