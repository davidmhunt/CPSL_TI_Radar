# IWR6843ISK-ODS antenna geometry and TX order (gui-25 Step 1)

**Date:** 2026-10-07
**Memo:** docs/research/iwr6843_ods_antenna_2026-10-07.md

## Question as asked

For directive gui-25: give the IWR6843ISK-ODS antenna geometry (TX1/TX2/TX3 and RX1-RX4 positions in units of $\lambda$), which TX mask bits (1, 2, 4) form azimuth versus elevation virtual pairs, and whether chirp TX order 1,2,4 is a hardware requirement of the ODS layout or just the shipped cfgs' choice (versus the GUI's 1,4,2 convention for the standard IWR6843ISK). Also list the shipped ODS cfgs and their chirp masks. Out of scope: AOP board, angle-resolution maths.

## TL;DR

On the ODS, **TX1 and TX2 are the azimuth pair ($\lambda$ apart horizontally, same height) and TX2 and TX3 are the elevation pair ($\lambda$ apart vertically, same column)**. Mask bits: 1 and 2 = azimuth, 4 = elevation. This differs from the standard ISK, where TX1 and TX3 (bits 1, 4) are azimuth and TX2 (bit 2) is the elevation TX. So "azimuth TX first, elevation TX last" is **1,2,4 on the ODS** and 1,4,2 on the ISK; the shipped ODS cfgs already follow that rule. TI's guide does not state a hardware requirement on chirp order; whether the SDK demo requires it is not sourced here. The RX array is a 2x2 square at $\lambda/2$ pitch, and RX2/RX3 are 180 degrees out of phase with RX1/RX4.

## Evidence

All geometry is from TI SWRU546E (`ti_swru546e_evms`), section 3.7 "IWR6843ISK-ODS Antenna", Figures 3-16 and 3-17, p. 40 (a local copy is in `docs/references/`). The figures are images; positions below were read from the annotated Figure 3-17 (dimension marks $\lambda/2$ and $\lambda$, "$\lambda$ = 5mm").

**Positions** (x = azimuth, z = elevation; origin RX1; $\lambda$ = 5 mm at 60 GHz). Figure 3-17 / p. 40. Confidence H for relative layout, M for the exact absolute offsets of the TX group from the RX group (not dimensioned in the figure).

| Antenna | x | z |
|---|---|---|
| RX1 | 0 | 0 (top row) |
| RX4 | $+\lambda/2$ | 0 (top row) |
| RX2 | 0 | $-\lambda/2$ (bottom row) |
| RX3 | $+\lambda/2$ | $-\lambda/2$ (bottom row) |
| TX1 | $x_0$ | $z_0$ |
| TX2 | $x_0+\lambda$ | $z_0$ |
| TX3 | $x_0+\lambda$ | $z_0-\lambda$ |

Figure 3-17 dimensions: RX1-RX4 marked $\lambda/2$; TX1-TX2 marked $\lambda$ (horizontal); TX2-TX3 marked $\lambda$ (vertical). RX numbering is a 2x2 block: RX1 top-left, RX4 top-right, RX2 bottom-left, RX3 bottom-right (Figure 3-16 labels).

**Virtual array** (Figure 3-17, right panel, 12 channels, "4 x 3 virtual antennas positions", sec. 3.7 text; H). Each TX block is the 2x2 RX square translated by that TX:
- TX1 block (ch 1,4 top; 2,3 bottom) at columns 0, $\lambda/2$; TX2 block (ch 5,8 top; 6,7 bottom) at columns $\lambda$, $3\lambda/2$ (same rows). TX1+TX2 therefore form a contiguous 4-wide x 2-high array ($\lambda/2$ pitch). So TX1/TX2 = azimuth pair.
- TX3 block (ch 9,12 top; 10,11 bottom) sits directly **below** the TX2 block (same columns, shifted down by $\lambda$ = one block height). So TX2/TX3 = elevation pair.
- Channel numbering in the figure: 1-4 = TX1-RX1, RX2, RX3, RX4 (in the layout order 1,4 / 2,3), 5-8 = TX2, 9-12 = TX3.
- Figure note (H): "RX2 and RX3 are 180 degrees out of phase with respect to RX1 and RX4. Because of this, a 180 degree phase inversion needs to be applied in software processing for the corresponding virtual RX channels (highlighted in Red)" (red = channels 2,3,6,7,10,11). This matters for any angle processing, not for the GUI cfg editing.

**Standard ISK for contrast** (SWRU546E sec. 3.6 / Figure 3-9, p. 38; H): RX1-RX4 in a row at $\lambda/2$; TX1, TX2, TX3 along the top with TX2 raised by $\lambda/2$ in elevation relative to TX1 and TX3 (Figure 3-9 marks $\lambda$ and $\lambda/2$). Virtual array channels 1-4 = TX1, 9-12 = TX3 (azimuth, 8 wide) and 5-8 = TX2 (the elevation row). So on the ISK the elevation TX is TX2 (bit 2) and azimuth is TX1+TX3 (bits 1+4), which is why TI's 3D profile lists 1,4,2 (`docs/research/gui_multichirp_tdm.md:34`, citing SDK `profile_3d.cfg`).

**Is 1,2,4 a hardware requirement?** SWRU546E says nothing about chirp ordering for the ODS (searched sec. 3.7 and the ISK-ODS deprecated copy sec. 6.7). Physically, TDM-MIMO with one TX active per chirp works for any order; the ordering only affects which slot a software decoder assigns to which virtual-array channel. Any requirement would come from the SDK demo's antenna-geometry table (TI's `antenna_geometry.c`, referred to in SWRA656C for the AOP, https://ti.com/document-viewer/lit/html/SWRA656C/GUID-282BD0FB-C19E-4482-92E6-53663DE4907F; M that such a table exists for ISK variants), which I could not read for the ODS. The E2E forum threads on ODS chirp setting returned HTTP 403 and were not read. **Not sourced; inference only (L-M):** the shipped ODS cfgs list azimuth TX first and elevation TX last, matching the ISK rule, with the ODS elevation TX being TX3.

**Shipped ODS cfgs** (repo, all `channelCfg 15 7 0`, i.e. TX mask 7, chirps `chirpCfg 0..2` with masks 1, 2, 4 in that order; H):
- `CPSL_TI_Radar_cpp/config/radar/nav_configs/6843_RadVel_ods_{5,10,20}Hz.cfg` lines 10, 14-16
- `CPSL_TI_Radar_cpp/config/radar/nav_configs/6843_IcaRAus_ods_10Hz.cfg` lines 10, 14-16
- `CPSL_TI_Radar_cpp/config/radar/IWR_Demos/rad_nav_configs/6843_ODS_lr_CFAR_{7,10}dB.cfg` lines 4, 8-10
- System configs referencing them (`CPSL_TI_Radar_cpp/config/system/`, `radar_cfg` line 4 or similar): `down_radar_IWR6843_ods_dca_RadVel.json`, `radar_0_IWR6843_ods_human_movement.json`, `radar_0_IWR6843_ods_dca_RadVel.json`, `down_radar_6843_RadVel_ods_10Hz.json` (all `6843_RadVel_ods_10Hz.cfg`) and `down_radar_6843_IcaRAus_ods_10Hz.json` (`6843_IcaRAus_ods_10Hz.cfg`). All five use TX masks 1,2,4 (H).

Repo status of the rule: `radar_gui/cfg/validate.py:208-214` warns when `0b010 in first and first[-1] != 0b010`, i.e. it hard-codes "TX2 is the elevation TX", which is wrong for the ODS; `radar_gui/cfg/metrics.py:319,330` already notes ODS layout differs (unverified).

## Applicability to CPSL TI Radar

Established (from TI): the ODS has elevation TX = TX3 (bit 4), azimuth TX = TX1 + TX2 (bits 1, 2). The current `tx_order_convention` rule keys on bit 2 as elevation, so it fires falsely on the shipped ODS cfgs (1,2,4: TX2 is not last).

Recommended encoding for Step 2 (Coder):
1. Board descriptor `IWR6843ODS` carries a GUI-only "elevation TX bit" (ODS: 4; ISK/BOOST: 2) or equivalently a `tx_order` convention string (ODS: `1,2,4`; IWR6843: `1,4,2`). Rule: warn if the elevation TX is present in the loop and is not last. This reproduces both conventions from one field.
2. Geometry fields (optional, FUTURE gui-12; out of scope for now but record them): RX positions in $\lambda/2$ units `[(0,0),(0,-1),(1,-1),(1,0)]` for RX1..RX4 (x right, z up) and TX positions in $\lambda/2$ units `TX1=(0,0), TX2=(2,0), TX3=(2,-2)` relative to each other (the TX-to-RX offset is not dimensioned in the figure and is irrelevant to the virtual array shape). Azimuth pair = {TX1, TX2}, elevation pair = {TX2, TX3}. A 3-TX ODS gives a 4x2 azimuth array plus 2 elevation rows, not 12 in a line, so `az_res` (`metrics.py`, "n_az = az_tx * n_rx") should use az_tx = 2 and the ISK-style count only coincides numerically.
3. Message text should say "elevation TX3" for the ODS; keep the existing text for the ISK.
4. Keep the severity low; the order is a convention, not a proven requirement, consistent with the existing `validate.py` wording ("unverified").

## Recommended Experiment

Optional bench check (needs an ODS board, out of directive scope): run the 1,2,4 cfg and a 1,4,2 cfg with the SDK out-of-box demo/people-counting firmware on a corner reflector at known elevation; compare elevation estimates. This discriminates whether the demo firmware's antenna table assumes a fixed slot order. Otherwise only reading the SDK's ODS antenna-geometry table (or TI's confirmation) settles it.

## Confidence

- Positions, azimuth/elevation pairing, 12-channel virtual array: high (TI guide figure, annotated dimensions), caveat that I read them from a raster figure, not a table.
- 1,2,4 = "azimuth first, elevation last" on the ODS: high as a derived statement from the pairing; the claim that TI's firmware requires it: **not settled** (TI text silent; SDK source and E2E threads not read).
- Exact TX-to-RX absolute offsets: not given; not needed for the virtual array.

## Sources

- `ti_swru546e_evms` — Texas Instruments (2022), "60GHz mmWave Sensor EVMs (xWR6843ISK / IWR6843ISK-ODS, IWR6843AOPEVM, MMWAVEICBOOST), SWRU546E". url:https://www.ti.com/lit/ug/swru546e/swru546e.pdf
