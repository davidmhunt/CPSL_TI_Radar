# Validation bench results

Raw CSV/JSON output of the bench runs (`tools/bench`), one file pair per rep.

- `validation_iwr1843_dca_core16__*`, `validation_iwr1843_serial_core16__*`: validation runs of the C++ driver at its serial-latency fix (DCA1000 and serial).
- `ab_iwr1843_dca_nocap__*`, `ab2_iwr1843_dca_nocap__*`: with/without cap_sys_nice A/B. `ab_` rep 3 is a start-timeout failure (cause unexplained at the time; likely overlapping reps, unverified).
- `core20_iwr1843_dca_default__*`: default no-cap build after the later driver change. Rep 2 is a bind error because it was launched while rep 1 still ran (bench spacing mistake, not driver/board).
