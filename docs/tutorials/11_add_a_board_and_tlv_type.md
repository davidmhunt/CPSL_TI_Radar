# 11. Add a board, add a TLV type

Two small changes, each with a test; the last section undoes both. Run from the repository root, with the build from [tutorial 1](01_install.md).

## Add or tune a board (no rebuild of the driver)

A board descriptor is one JSON file in `CPSL_TI_Radar_cpp/config/boards/`; the file name must equal its `"name"`. This creates `TOY1843`, an IWR1843 with a slower CLI timeout, and a system config that uses it:

```bash
cd CPSL_TI_Radar_cpp
sed 's/"name": "IWR1843"/"name": "TOY1843"/; s/"cmd_timeout_ms": 100/"cmd_timeout_ms": 300/' \
    config/boards/IWR1843.json > config/boards/TOY1843.json
sed 's/"board": "IWR1843"/"board": "TOY1843"/' config/system/IWR1843_demo_tlv_default.json > config/system/toy_1843.json
./build/CPSL_TI_Radar_CPP config/system/toy_1843.json --validate | grep -E '^(board|cli)|OK'
cd ..
```

The `cli:` line must now say `300 ms per command`. Fields and where each value comes from: `config/boards/README.md`. To change one value for one run only, use `"board_overrides"` in the system config instead of a new file. A new serial dialect or LVDS layout needs code, not just JSON.

Now pin it with a test. In `CPSL_TI_Radar_cpp/tests/test_board_descriptor.cpp`, add this above `TEST_CASE(loads_IWR6843)`:

```cpp
TEST_CASE(loads_TOY1843) {
    BoardDescriptor d = must_load("TOY1843");
    CHECK_EQ(d.cli.cmd_timeout_ms, 300u);
    CHECK(d.data_uart.tlv_dialect == TlvDialect::sdk3);
}
```

```bash
cmake --build CPSL_TI_Radar_cpp/build -j --target test_board_descriptor
ctest --test-dir CPSL_TI_Radar_cpp/build -R test_board_descriptor --output-on-failure
```

It must report `100% tests passed`.

## Add a TLV type to a serial dialect

The demo sends each frame as a header followed by `{type, length, payload}` TLVs. `parse_uart_frame` in `src/SerialStreamer/UartFrame.cpp` is a pure function (bytes in, `UartFrame` out, no I/O), so a new TLV is one change there plus one test with a synthetic frame. Example: decode the cascade demo's stats TLV (type 6, six `uint32`, layout in the optional `firmware_dev/` submodule, `firmware_dev/projects/awr2243_cascade_ddm/src/ti/demo/am273x/mmw/include/mmw_output.h`), keeping the first field.

1. `src/SerialStreamer/UartFrame.hpp`, in `struct UartFrame`, add `bool has_stats = false;` and `uint32_t inter_frame_processing_us = 0;` right after `has_side_info` (above the comment on `compact_points_skipped`, which stays attached to that field).
2. `src/SerialStreamer/UartFrame.cpp`: add `constexpr uint32_t kTlvStats = 6;` beside `kTlvSideInfo`; add `out.has_stats = false;` beside `out.compact_points_skipped = false;` at the top of `parse_uart_frame`; and in the TLV loop add this branch just before the `kTlvCascadeCompactPoints` one. The snippet's first line closes the previous branch and its last line leaves the block open; the existing `} else if (type == kTlvCascadeCompactPoints ...` below it closes it:

```cpp
        } else if (type == kTlvStats && dialect == TlvDialect::mcuplus_cascade) {
            if (length != 24) return bad("stats TLV (type 6) has " + std::to_string(length) + " bytes, not 24");
            out.inter_frame_processing_us = uart_le32(data, off + 8);
            out.has_stats = true;
```

The loop has already checked that the TLV fits in the frame; validate only the length you expect, and never read past it.

3. `tests/test_uart_parse.cpp`, above `TEST_MAIN()`: the helpers `make_frame`, `points_tlv` and `put_u32` are in `tests/uart_test_frames.hpp`.

```cpp
TEST_CASE(cascade_stats_tlv_is_decoded) {
    Tlv st{TLVCodes::STATS, {}};
    for (uint32_t v : {1234u, 0u, 0u, 0u, 0u, 0u}) put_u32(st.payload, v);
    auto r = parse_uart_frame(make_frame(1, {points_tlv(2, 0.f), st}), TlvDialect::mcuplus_cascade);
    CHECK(static_cast<bool>(r));
    if (!r) return;
    CHECK(r->has_stats);
    CHECK_EQ(r->inter_frame_processing_us, 1234u);
}
```

```bash
cmake --build CPSL_TI_Radar_cpp/build -j && ctest --test-dir CPSL_TI_Radar_cpp/build --output-on-failure
```

All tests must pass. For a real new dialect, add a `TlvDialect` value, its header size (`uart_header_bytes`) and a golden frame written out byte by byte, as `sdk3_golden_frame_from_literal_bytes` does.

## Undo the exercise

```bash
rm CPSL_TI_Radar_cpp/config/boards/TOY1843.json CPSL_TI_Radar_cpp/config/system/toy_1843.json
git restore CPSL_TI_Radar_cpp/tests CPSL_TI_Radar_cpp/src
```
