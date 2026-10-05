# Cascade Radar: Hardware Setup Guide

This guide covers getting the **AWR2243 2-chip cascade board** running, from plugging it in to seeing radar
points in the C++ driver. Go through the steps in order and tick each box as you finish it.

> Tip: in VS Code, press `Ctrl+Shift+V` to view this file formatted.

---

## What you need

- [ ] The TI cascade dev board
- [x] A micro-USB cable, to connect the board to this computer
- [x] **A 12 V power supply**: more than 2 A, 2.1 mm barrel plug, center-positive.
      **USB alone can't power the board.** The board's USB chip (an XDS110) runs off the 12 V supply too,
      so **the board doesn't show up on USB at all until 12 V is on.**
- [ ] This computer, with the Docker image already built (done in Phase 1)

---

## The two things to remember

**1. The J6 jumper sets the board's mode.**

```
   J6 jumper                    What the board does
   ─────────                    ───────────────────
   [ ]                          
   [■]  ← jumper on BOTTOM two  FLASH mode: ready to receive new firmware
   [■]
   
   [■]  ← jumper on TOP two     RUN mode: runs the radar demo
   [■]
   [ ]
```

Turn the 12 V off before moving the jumper, then turn it back on. The board only reads the jumper when it powers up.

**2. Power-cycle the board before every radar run.**
The demo accepts a configuration only **once** after power-up. Before each new run, turn the 12 V off and on again.

---

## Step 1: Find the board's USB ports (about 2 min) ✅ done 2026-10-01

1. Plug in the USB cable **and turn the 12 V on**. Without 12 V, no ports appear.
2. In a terminal, run:
   ```bash
   ls -l /dev/serial/by-id/
   ```
3. You should see **two** entries, each pointing to a port such as `ttyACM0` or `ttyUSB0`.
   - One is the **CLI port** (TI calls it "Application/User UART"). It's used for flashing and for sending settings.
     It's usually the **lower** number.
   - The other is the **data port**, where the radar points come out.
4. Write them down:

   | Port | Short name (e.g. `/dev/ttyACM0`) | Full by-id path |
   |---|---|---|
   | CLI port  | `/dev/ttyACM0` | `/dev/serial/by-id/usb-Texas_Instruments_XDS110__03.00.00.29__Embed_with_CMSIS-DAP_00000000-if00` |
   | Data port | `/dev/ttyACM1` | `/dev/serial/by-id/usb-Texas_Instruments_XDS110__03.00.00.29__Embed_with_CMSIS-DAP_00000000-if03` |

   Found on 2026-10-01. The board shows up as a TI **XDS110** (USB ID `0451:bef3`; `lsusb` calls it a
   "CC1352R1 Launchpad", which is just a shared ID). USB interface `if00` is TI's Application/User UART (CLI)
   and `if03` is the Auxiliary Data Port. Both ports are owned by group `plugdev`; your user is in `plugdev`
   and `dialout`, and the `flash` container runs as root, so both ports open fine with no extra setup.

If you're not sure which is which, guess. A wrong guess only means a step fails, and then you swap them.

**Nothing shows up?** Try a different cable, because some micro-USB cables are charge-only. Also try a different USB port.

---

## Step 2: Flash TI's ready-made firmware (about 5 min) ✅ done 2026-10-01

Start with TI's own firmware. If this works, you know the board, cable, and ports are good.

1. Turn the 12 V **off**.
2. Put the J6 jumper on the **bottom two pins** (FLASH mode).
3. Make sure USB is connected, then turn the 12 V **on**.
4. Run this, replacing `/dev/ttyACM0` with **your CLI port**:
   ```bash
   cd ~/Documents/radar_dev/CPSL_TI_Radar/firmware_dev
   docker compose run --rm flash /build_context/scripts/flash_cascade.sh /dev/ttyACM0 prebuilt
   ```
5. Wait about a minute. ✅ **Success** looks like this:
   ```
   All commands from config file are executed !!!
   Flash OK. Move J6 to the top two pins (QSPI boot) and power-cycle the board.
   ```

❌ **It failed?** Check that the jumper is on the bottom pins, power-cycle, and try again. If it still fails,
try the **other** port. More help is in [Troubleshooting](#troubleshooting).

---

## Step 3: Check that the radar works (about 2 min) ✅ done 2026-10-01

1. Turn the 12 V **off**.
2. Move the J6 jumper to the **top two pins** (RUN mode).
3. Turn the 12 V **on**.
4. Run this, replacing the ports with **yours**:
   ```bash
   cd ~/Documents/radar_dev/CPSL_TI_Radar/firmware_dev
   docker compose run --rm flash python3 /build_context/scripts/cascade_serial_check.py \
       --cli /dev/ttyACM0 --data /dev/ttyACM1 \
       --cfg /build_context/firmware/cascade/src/demo/chirp_configs/cascade_shortrange.cfg
   ```
5. ✅ **Success** looks like this:
   - Every settings line starts with `Done`
   - Then about 10 seconds of lines like `frame 123 ... points= 12 ...`
   - The last line shows about **20 Hz** with **0 frame-number gaps** and **0 framing errors**

🎉 If this works, the hardware works. The remaining steps use **our** firmware and the C++ driver.

---

## Step 4: Flash and check OUR firmware (about 7 min) ✅ done 2026-10-01

This is the same as Steps 2 and 3, but **leave off the word `prebuilt`**:

1. 12 V **off**, jumper on the **bottom** pins, 12 V **on**.
2. Flash:
   ```bash
   cd ~/Documents/radar_dev/CPSL_TI_Radar/firmware_dev
   docker compose run --rm flash /build_context/scripts/flash_cascade.sh /dev/ttyACM0
   ```
3. 12 V **off**, jumper on the **top** pins, 12 V **on**.
4. Run the same check command as in Step 3. The results should look the same as with TI's firmware.

---

## Step 5: Run the C++ radar driver (about 5 min)

1. **One-time setup:** give your user access to serial ports.
   ```bash
   groups
   ```
   If `dialout` isn't in the list, run the following command, then **log out and log back in**:
   ```bash
   sudo usermod -a -G dialout $USER
   ```
2. **One-time setup** (✅ done 2026-10-01, by-id paths from Step 1 are filled in): open this file in VS Code:
   `CPSL_TI_Radar/CPSL_TI_Radar_cpp/config/system/radar_0_AWR2243_cascade_serial.json`
   Then replace the two port names with your **full by-id paths** from Step 1. Those paths stay the same every
   time you plug in, unlike `ttyACM0`:
   ```json
   "CLI_port": "/dev/serial/by-id/...CLI port path...",
   ...
   "data_port": "/dev/serial/by-id/...data port path...",
   ```
3. **Power-cycle the board.** The jumper stays on the top pins.
4. Run:
   ```bash
   cd ~/Documents/radar_dev/CPSL_TI_Radar/CPSL_TI_Radar_cpp/build
   ./CPSL_TI_Radar_CPP ../config/system/radar_0_AWR2243_cascade_serial.json
   ```
5. ✅ **Success:** about 20 lines per second like this:
   ```
   TLV frame 57: 14 detected points (first: x=0.31 y=2.05 z=0.02 v=0)
   ```
6. Press `Ctrl+C` to stop. **Power-cycle the board before running again.**

**Final test:** leave it running for a few minutes. You should see **no** `frame number jumped` messages and
**no** `Timeout` messages.

---

## Troubleshooting

| What you see | What to try |
|---|---|
| No ports in `/dev/serial/by-id/` | Is the **12 V on**? The board's USB chip needs it. Then try a different USB cable (it must carry data), or a different USB port. |
| `serial port ... not found` | Check the port name from Step 1, and make sure the cable is plugged in. |
| `Permission denied` on the port | Do the `dialout` setup in Step 5.1, then log out and back in. |
| Flashing fails within a second with `expected ACK; got b'C'` | The script now handles this by clearing stale bytes before each send. If it still happens: power-cycle (jumper on the bottom pins) and run it again. |
| Flashing fails or hangs | Jumper on the **bottom** pins? Power-cycle and retry. Try the other port. |
| Flashing keeps failing on a new board | The board's flash chip may need a setting turned on ("Quad Enable" in TI's guide). Ask Claude for help with this one. |
| No `Done` replies, or `FAIL` on the first line | Jumper on the **top** pins? Ports swapped? Power-cycle and retry. |
| `Done` works, but the first line fails after an earlier run | The board was already configured. **Power-cycle it.** |
| C++ driver says `power-cycle the EVM` | Same as above: power-cycle and run again. |
| `Done` works but **no frames** | Data port is wrong (swap the ports). If the ports are right, the USB chip may not support the fast data speed (3,125,000 baud). Ask Claude to lower the speed in the firmware. |
| Frames arrive but there are gaps or framing errors | Note how often it happens and send the output to Claude. |

---

## Progress checklist

- [x] Step 1: Found both ports (`ttyACM0` = CLI, `ttyACM1` = data)
- [x] Step 2: TI firmware flashed
- [x] Step 3: TI firmware streams about 20 Hz with no gaps (200 frames, 20.03 Hz, 0 gaps, 0 framing errors, ~55–80 points/frame)
- [x] Step 4: Our firmware flashed and streams the same (20.02 Hz, 0 gaps, 0 framing errors)
- [ ] Step 5: C++ driver prints points for several minutes with no errors (75 s clean on TI firmware 2026-10-01: 1479 frames, 0 gaps; full multi-minute soak still to do)

When everything is ticked, the hardware part of `CASCADE_PLAN.md` (Phases 2–4) is done.
