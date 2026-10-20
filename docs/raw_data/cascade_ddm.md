# AWR2243 cascade DDM

Only what differs from the [pipeline](README.md). **Raw LVDS ADC streaming from this firmware is unverified: nothing here was run, and no raw capture exists.** [F5]

- The shipped DDM image has no raw ADC LVDS stream: `mmw_lvds_stream.c` is excluded from the build and `LVDS_STREAM` is defined nowhere. [F5]
- The board descriptor for the cascade says `"lvds": { "supported": false }`, so the driver has no LVDS layout for it. [F5]
- An archived firmware-repo note describes a raw stream but is itself marked "not verified against source". Do not rely on it. [F5]
- That note's packet figures (payload 1456 B, 4 B + 4 B + 2 B header) disagree with TI's DCA1000 guide (1462 B, 4 B + 6 B) and with our code; the TI figures are the ones used in the [pipeline](README.md#6-dca1000-to-udp). [V7]

## Known gaps

- Whether a cascade raw stream exists, its lane count, sample order and packet size: unknown. The interface control document (rev 2.23) was not available to check. [F5]
