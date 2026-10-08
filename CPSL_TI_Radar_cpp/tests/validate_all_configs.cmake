# test_validate_all_configs (directive core-10): run the driver's --validate
# path over every tracked system config, and check the two fixed outcomes:
#   - every config/system/*.json exits 0 (schema v2, board descriptor, radar cfg
#     cross-checks, frame shape)
#   - an IWR1843 config does not skip calibData (the SDK 3.6 demo needs it)
#   - a v1 file exits non-zero and names the migration script
#   - output.dir under a regular file fails and names the path (core-13)
#   - at the default log level nothing but the summary is printed: no
#     "[RadarConfig]" load chatter (core-13)
# Invoked by ctest with -DDRIVER=<binary> -DCONFIG_DIR=<config> -DV1_FIXTURE=<v1 .json>
# -DTMP_DIR=<scratch dir>.

file(GLOB configs "${CONFIG_DIR}/system/*.json")
list(LENGTH configs n)
if(n LESS 40)
  message(FATAL_ERROR "expected at least 40 tracked system configs, found ${n}")
endif()

set(failed 0)
foreach(cfg IN LISTS configs)
  execute_process(COMMAND "${DRIVER}" --validate "${cfg}"
                  RESULT_VARIABLE rc OUTPUT_VARIABLE out ERROR_VARIABLE err)
  get_filename_component(name "${cfg}" NAME)
  if(rc EQUAL 0 AND "${out}${err}" MATCHES "\\[RadarConfig\\]")
    message(STATUS "FAIL  ${name} (printed load chatter)\n${out}${err}")
    math(EXPR failed "${failed} + 1")
  elseif(rc EQUAL 0)
    message(STATUS "ok    ${name}")
  else()
    message(STATUS "FAIL  ${name} (exit ${rc})\n${out}${err}")
    math(EXPR failed "${failed} + 1")
  endif()
endforeach()
if(failed GREATER 0)
  message(FATAL_ERROR "${failed} of ${n} system configs failed --validate")
endif()

execute_process(COMMAND "${DRIVER}" --validate "${CONFIG_DIR}/system/IWR1843_demo_stress_test_baseline_front.json"
                RESULT_VARIABLE rc OUTPUT_VARIABLE out ERROR_VARIABLE err)
if(NOT rc EQUAL 0 OR out MATCHES "skipped: +calibData")
  message(FATAL_ERROR "IWR1843 --validate skips calibData (it must be sent):\n${out}${err}")
endif()

# core-22: the SAR system config validates (exit 0 is covered by the glob above);
# the same board with a stock cfg is rejected naming the forbidden command
execute_process(COMMAND "${DRIVER}" --validate "${CONFIG_DIR}/system/IWR1843_iwr1843_sar_lvds_SAR_2ms.json"
                RESULT_VARIABLE rc OUTPUT_VARIABLE out ERROR_VARIABLE err)
if(NOT rc EQUAL 0)
  message(FATAL_ERROR "SAR system config failed --validate (exit ${rc}):\n${out}${err}")
endif()
file(REMOVE_RECURSE "${TMP_DIR}")
file(MAKE_DIRECTORY "${TMP_DIR}")
file(READ "${CONFIG_DIR}/system/IWR1843_iwr1843_sar_lvds_SAR_2ms.json" j)
string(JSON j SET "${j}" radar_cfg "\"${CONFIG_DIR}/radar/IWR1843/demo/RadVel.cfg\"")
string(JSON j SET "${j}" board "\"${CONFIG_DIR}/boards/IWR1843_SAR.json\"")
file(WRITE "${TMP_DIR}/sar_stock_cfg.json" "${j}")
execute_process(COMMAND "${DRIVER}" --validate "${TMP_DIR}/sar_stock_cfg.json"
                RESULT_VARIABLE rc OUTPUT_VARIABLE out ERROR_VARIABLE err)
if(rc EQUAL 0 OR NOT "${out}${err}" MATCHES "forbidden")
  message(FATAL_ERROR "IWR1843_SAR with a stock cfg was not rejected naming a forbidden command (exit ${rc}):\n${out}${err}")
endif()

execute_process(COMMAND "${DRIVER}" --validate "${V1_FIXTURE}"
                RESULT_VARIABLE rc OUTPUT_VARIABLE out ERROR_VARIABLE err)
if(rc EQUAL 0 OR NOT err MATCHES "tools/migrate_config_v1_to_v2.py")
  message(FATAL_ERROR "v1 file was not rejected with the migration hint (exit ${rc}):\n${out}${err}")
endif()

# output.dir under a regular file: a copy of a tracked config with absolute paths
file(REMOVE_RECURSE "${TMP_DIR}")
file(MAKE_DIRECTORY "${TMP_DIR}")
file(WRITE "${TMP_DIR}/a_file" "x")
file(READ "${CONFIG_DIR}/system/IWR1843_demo_stress_test_front.json" j)
string(JSON radar_cfg GET "${j}" radar_cfg)
string(JSON j SET "${j}" radar_cfg "\"${CONFIG_DIR}/system/${radar_cfg}\"")
string(JSON j SET "${j}" board "\"${CONFIG_DIR}/boards/IWR1843.json\"")
string(JSON j SET "${j}" output dir "\"${TMP_DIR}/a_file/captures\"")
file(WRITE "${TMP_DIR}/under_file.json" "${j}")
execute_process(COMMAND "${DRIVER}" --validate "${TMP_DIR}/under_file.json"
                RESULT_VARIABLE rc OUTPUT_VARIABLE out ERROR_VARIABLE err)
if(rc EQUAL 0 OR NOT err MATCHES "a_file/captures cannot be created: .*a_file is a file")
  message(FATAL_ERROR "output.dir under a file was not rejected with its path (exit ${rc}):\n${out}${err}")
endif()

# gui-04: --validate --json. Good config: exit 0, one JSON object with the specified shape.
execute_process(COMMAND "${DRIVER}" --validate --json "${CONFIG_DIR}/system/IWR1843_demo_stress_test_front.json"
                RESULT_VARIABLE rc OUTPUT_VARIABLE out ERROR_VARIABLE err)
if(NOT rc EQUAL 0 OR NOT "${err}" STREQUAL "")
  message(FATAL_ERROR "--validate --json failed on a good config (exit ${rc}):\n${out}${err}")
endif()
string(JSON ok GET "${out}" ok)
string(JSON board GET "${out}" board)
string(JSON n_err LENGTH "${out}" errors)
string(JSON n_warn LENGTH "${out}" warnings)
string(JSON n_notes LENGTH "${out}" notes)
string(JSON rx GET "${out}" frame rx)
string(JSON period GET "${out}" frame period_ms)
string(JSON bpf GET "${out}" bytes_per_frame)
string(JSON n_metrics LENGTH "${out}" metrics)
string(JSON cfgname GET "${out}" config)
string(JSON fw ERROR_VARIABLE fw_err GET "${out}" firmware)
if(NOT ok STREQUAL "ON" AND NOT ok STREQUAL "true" OR NOT board STREQUAL "IWR1843" OR NOT n_err EQUAL 0
   OR NOT rx GREATER 0 OR NOT bpf GREATER 0 OR NOT cfgname MATCHES "IWR1843_demo_stress_test_front.json$")
  message(FATAL_ERROR "--validate --json good-config shape is wrong:\n${out}")
endif()
# gui-04 Step 3b: metrics carry the cfg limit numbers; warning-level limits land in warnings[], not errors[]
string(JSON m_rx GET "${out}" metrics n_rx)
string(JSON m_bpf GET "${out}" metrics bytes_per_frame)
if(NOT m_rx EQUAL rx OR NOT m_bpf EQUAL bpf)
  message(FATAL_ERROR "--validate --json metrics disagree with frame (n_rx ${m_rx} vs ${rx}, bytes ${m_bpf} vs ${bpf}):\n${out}")
endif()
execute_process(COMMAND "${DRIVER}" --validate --json "${CONFIG_DIR}/system/IWR1843_demo_vel_sr.json"
                RESULT_VARIABLE rc OUTPUT_VARIABLE wout ERROR_VARIABLE werr)
string(JSON wcode GET "${wout}" warnings 0 code)
string(JSON werrs LENGTH "${wout}" errors)
if(NOT rc EQUAL 0 OR NOT wcode STREQUAL "band_edge" OR NOT werrs EQUAL 0)
  message(FATAL_ERROR "a warning-level limit must be a warning, not an error (exit ${rc}):\n${wout}")
endif()
# the text summary must not leak into the JSON output
if(out MATCHES "OK:" OR out MATCHES "bytes/frame:")
  message(FATAL_ERROR "--validate --json printed text output:\n${out}")
endif()

# Bad config: exit 1, ok false, one error with code + message + source.
file(READ "${CONFIG_DIR}/system/IWR1843_demo_stress_test_front.json" j)
string(JSON radar_cfg GET "${j}" radar_cfg)
string(JSON j SET "${j}" radar_cfg "\"${CONFIG_DIR}/system/${radar_cfg}\"")
string(JSON j SET "${j}" board "\"${CONFIG_DIR}/boards/IWR1843.json\"")
string(JSON j SET "${j}" firmware "\"iwr1843_sar_lvds\"")
file(WRITE "${TMP_DIR}/alias_bad.json" "${j}")
execute_process(COMMAND "${DRIVER}" --validate --json "${TMP_DIR}/alias_bad.json"
                RESULT_VARIABLE rc OUTPUT_VARIABLE out ERROR_VARIABLE err)
string(JSON ok GET "${out}" ok)
string(JSON code GET "${out}" errors 0 code)
string(JSON msg GET "${out}" errors 0 message)
string(JSON src GET "${out}" errors 0 source)
string(JSON fw GET "${out}" firmware)
if(rc EQUAL 0 OR NOT (ok STREQUAL "OFF" OR ok STREQUAL "false") OR NOT code STREQUAL "firmware_alias"
   OR NOT msg MATCHES "runs with board IWR1843_SAR" OR NOT src MATCHES "iwr1843_sar_lvds.json$"
   OR NOT fw STREQUAL "iwr1843_sar_lvds")
  message(FATAL_ERROR "--validate --json bad-config shape is wrong (exit ${rc}):\n${out}")
endif()
# a file that does not parse is still one JSON object with ok false
execute_process(COMMAND "${DRIVER}" --validate --json "${V1_FIXTURE}"
                RESULT_VARIABLE rc OUTPUT_VARIABLE out ERROR_VARIABLE err)
string(JSON code GET "${out}" errors 0 code)
string(JSON msg GET "${out}" errors 0 message)
if(rc EQUAL 0 OR NOT code STREQUAL "config_invalid" OR NOT msg MATCHES "tools/migrate_config_v1_to_v2.py")
  message(FATAL_ERROR "--validate --json on a v1 file is wrong (exit ${rc}):\n${out}")
endif()
# --json without --validate is a usage error
execute_process(COMMAND "${DRIVER}" --json "${CONFIG_DIR}/system/IWR1843_demo_stress_test_front.json"
                RESULT_VARIABLE rc OUTPUT_VARIABLE out ERROR_VARIABLE err)
if(NOT rc EQUAL 2)
  message(FATAL_ERROR "--json without --validate should exit 2, got ${rc}")
endif()
# the usage text keeps the flags the GUI detects
execute_process(COMMAND "${DRIVER}" --help RESULT_VARIABLE rc OUTPUT_VARIABLE out ERROR_VARIABLE err)
foreach(flag --skip-configure --tap-fd --tap-adc-every --json)
  if(NOT "${out}${err}" MATCHES "${flag}")
    message(FATAL_ERROR "usage text lost ${flag}")
  endif()
endforeach()

execute_process(COMMAND "${DRIVER}" RESULT_VARIABLE rc OUTPUT_VARIABLE out ERROR_VARIABLE err)
if(rc EQUAL 0 OR NOT err MATCHES "usage:")
  message(FATAL_ERROR "no-argument run did not print usage and fail (exit ${rc})")
endif()

message(STATUS "${n} configs validated; calibData not skipped, v1 rejection, output.dir under a file and usage checked")
