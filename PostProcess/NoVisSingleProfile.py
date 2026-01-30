import numpy as np
from MMWaveDevice import MMWaveDevice
from scipy.signal import find_peaks
from sklearn.cluster import DBSCAN

timestamps = []

def read_adc_data(adc_data_bin_file, mmwave_device):
    num_samples = mmwave_device.num_sample_per_chirp
    num_chirps = mmwave_device.num_chirp_per_frame
    num_frames = mmwave_device.num_frame
    num_rx = mmwave_device.num_rx_chnl
    num_lanes = 4

    adc_data = np.fromfile(adc_data_bin_file, dtype=np.int16)
    expected_size = num_samples * num_chirps * num_frames * num_rx * 2

    print(f"ADC data size: {adc_data.size}, expected size: {expected_size}")

    if adc_data.size != expected_size:
        raise ValueError(f"Size of the adc data ({adc_data.size}) does not match the expected size ({expected_size})")

    if mmwave_device.adc_bits != 16:
        l_max = 2**(mmwave_device.adc_bits - 1) - 1
        adc_data[adc_data > l_max] -= 2**mmwave_device.adc_bits

    if mmwave_device.is_iq_swap:
        adc_data = adc_data.reshape(-1, num_lanes).T
    else:
        adc_data = adc_data.reshape(-1, num_lanes * 2).T
        adc_data = adc_data[:num_lanes] + 1j * adc_data[num_lanes:]

    adc_data = adc_data.T.flatten()

    adc_data = adc_data.reshape((num_frames, num_chirps, num_samples, num_rx)).transpose(2, 1, 0, 3)
    return adc_data

def cfar_ca1d(magnitude, num_train, num_guard, rate_fa):
    n = len(magnitude)
    alpha = num_train * (rate_fa ** (-1 / num_train) - 1)
    peak_idx = []

    for i in range(num_guard, num_train + num_guard):
        lagging_train = magnitude[i + num_guard + 1:i + num_guard + 1 + num_train]
        noise_level = np.sum(lagging_train) / num_train
        threshold = alpha * noise_level
        if magnitude[i] > threshold:
            peak_idx.append(i)

    for i in range(num_train + num_guard, n - num_train - num_guard):
        leading_train = magnitude[i - num_train - num_guard:i - num_guard]
        lagging_train = magnitude[i + num_guard + 1:i + num_guard + 1 + num_train]
        noise_level = (np.sum(leading_train) + np.sum(lagging_train)) / (2 * num_train)
        threshold = alpha * noise_level
        if magnitude[i] > threshold:
            peak_idx.append(i)

    for i in range(n - num_train - num_guard, n - num_guard):
        leading_train = magnitude[i - num_train - num_guard:i - num_guard]
        noise_level = np.sum(leading_train) / num_train
        threshold = alpha * noise_level
        if magnitude[i] > threshold:
            peak_idx.append(i)

    return np.array(peak_idx)

def analyze_periods(timestamps):
    timestamps = np.array([t[0] for t in timestamps])
    periods = np.diff(timestamps)

    periods_reshaped = periods.reshape(-1, 1)
    dbscan = DBSCAN(eps=0.005, min_samples=5).fit(periods_reshaped)
    labels = dbscan.labels_

    unique_labels, counts = np.unique(labels, return_counts=True)
    main_cluster_label = unique_labels[np.argmax(counts)]

    filtered_periods = periods[labels == main_cluster_label]
    outliers = periods[labels != main_cluster_label]

    unique_periods, counts = np.unique(filtered_periods, return_counts=True)

    return unique_periods, counts, outliers

def analyze_interference_batches(timestamps):
    batches = []
    batch_start_indices = [0]
    
    for i in range(1, len(timestamps)):
        if timestamps[i][0] - timestamps[i-1][0] > 50:  
            batch_start_indices.append(i)

    batch_start_times = [timestamps[i][0] for i in batch_start_indices]
    batch_periods = np.diff(batch_start_times)

    if len(batch_periods) == 0:
        return [], []

    batch_periods_reshaped = batch_periods.reshape(-1, 1)
    dbscan = DBSCAN(eps=0.1, min_samples=5).fit(batch_periods_reshaped)
    labels = dbscan.labels_

    unique_labels, counts = np.unique(labels, return_counts=True)
    main_cluster_label = unique_labels[np.argmax(counts)]

    filtered_batch_periods = batch_periods[labels == main_cluster_label]
    outliers = batch_periods[labels != main_cluster_label]

    unique_batch_periods, counts = np.unique(filtered_batch_periods, return_counts=True)

    return unique_batch_periods, counts, outliers

def process_adc_data(adc_data, num_samples, num_chirps, num_frames, rx_channel, sample_rate, frame_periodicity, idle_time, ramp_time, adc_start_time, mmwave_device):
    global timestamps

    for frame_idx in range(num_frames):
        for chirp_idx in range(num_chirps):
            chirp_data = adc_data[:, chirp_idx, frame_idx, rx_channel]

            time_per_sample = 1 / sample_rate
            start_time = frame_idx * frame_periodicity + chirp_idx * (idle_time + ramp_time) + (idle_time + adc_start_time)
            time_indices = start_time + np.arange(num_samples) * time_per_sample

            complex_magnitude = np.abs(chirp_data)
            
            num_train = 10
            num_guard = 2
            rate_fa = 1e-2
            
            peak_idx = cfar_ca1d(complex_magnitude, num_train, num_guard, rate_fa)

            for idx in peak_idx:
                if not any(np.isclose(time_indices[idx], t[0]) for t in timestamps):
                    timestamps.append((time_indices[idx], mmwave_device.freq / 1e9))

def main():
    adc_data_bin_file = '/Users/edwardju/Downloads/adc_data_Check5.bin'
    mmwave_setup_json_file = '/Users/edwardju/Downloads/Check5.mmwave.json'

    mmwave_device = MMWaveDevice(adc_data_bin_file, mmwave_setup_json_file)
    mmwave_device.print_device_configuration()

    adc_data = read_adc_data(adc_data_bin_file, mmwave_device)
    num_samples = mmwave_device.num_sample_per_chirp
    num_chirps = mmwave_device.num_chirp_per_frame
    num_frames = mmwave_device.num_frame
    rx_channel = 0

    sample_rate = mmwave_device.adc_samp_rate * 1000
    frame_periodicity = mmwave_device.frame_periodicity
    idle_time = mmwave_device.chirp_idle_time * 1e-3
    ramp_time = mmwave_device.chirp_ramp_time * 1e-3
    adc_start_time = mmwave_device.chirp_adc_start_time * 1e-3

    process_adc_data(adc_data, num_samples, num_chirps, num_frames, rx_channel, sample_rate, frame_periodicity, idle_time, ramp_time, adc_start_time, mmwave_device)

    if len(timestamps) > 1:
        timestamps.sort(key=lambda x: x[0])
        unique_periods, counts, outliers = analyze_periods(timestamps)
        print("Timestamps:", timestamps)
        print("Unique Periods:", unique_periods, "Counts:", counts)
        print("Outliers:", outliers)

        unique_batch_periods, batch_counts, batch_outliers = analyze_interference_batches(timestamps)
        print("Batch Periods:", unique_batch_periods, "Counts:", batch_counts)
        print("Batch Outliers:", batch_outliers)

if __name__ == "__main__":
    main()
