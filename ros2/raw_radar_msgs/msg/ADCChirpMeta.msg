# Per-chirp metadata of one ADCDataCube, from the iwr1843_sar_lvds firmware's
# LVDS dataFmt 2 (CPSL_TI_Radar ChirpMetaFrame). One message per cube, on a
# sibling topic; ADCDataCube itself is unchanged.
#
# header: the same stamp and frame_id as the cube it belongs to.
# Every per-chirp array below has one entry per chirp, in chirp order (the
# cube's "chirp" dimension), so index i here is chirp i of the cube.
std_msgs/Header header

# the driver's frame counter (AdcFrame::index, truncated to 32 bits)
uint32 frame_index

# per-chirp arrays
bool[]    record_valid         # the chirp's metadata record passed validation; if false the record fields are 0
bool[]    adc_complete         # every byte of the chirp's ADC block arrived (lost bytes are zeros)
uint16[]  flags                # record flags: 0x1 sat valid, 0x2 sat monitor on, 0x4 late, 0x8 skip, 0x10 resync
uint32[]  global_chirp_idx     # firmware chirp counter
uint16[]  run_idx              # firmware run index
uint64[]  ts_ticks             # chirp start, 10 ns ticks since boot
uint8[]   sat_slices           # saturation result of chirp (global_chirp_idx - sat_ref_lag), NOT of this chirp
uint8[]   sat_ref_lag
int16[]   sat_slices_aligned   # this chirp's own saturated slices, -1 = unknown (see prev_tail_sat)
bool[]    has_time             # t_s is known for this chirp
bool[]    time_interpolated    # t_s was interpolated because the record was invalid
float64[] t_s                  # seconds since the run's first valid record

# saturation results this frame carried for the previous frame's last two
# chirps: [1] = its last chirp, [0] = the one before; -1 = none
int16[2] prev_tail_sat

bool   run_known               # a record has fixed the run
uint16 run_idx_frame           # that run (valid if run_known)
uint32 records_valid
uint32 records_invalid
uint32 records_other_run
