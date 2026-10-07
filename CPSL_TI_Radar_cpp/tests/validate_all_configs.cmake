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

execute_process(COMMAND "${DRIVER}" --validate "${CONFIG_DIR}/system/front_radar_IWR1843_stress_test_baseline.json"
                RESULT_VARIABLE rc OUTPUT_VARIABLE out ERROR_VARIABLE err)
if(NOT rc EQUAL 0 OR out MATCHES "skipped: +calibData")
  message(FATAL_ERROR "IWR1843 --validate skips calibData (it must be sent):\n${out}${err}")
endif()

# core-22: the SAR system config validates (exit 0 is covered by the glob above);
# the same board with a stock cfg is rejected naming the forbidden command
execute_process(COMMAND "${DRIVER}" --validate "${CONFIG_DIR}/system/radar_0_IWR1843_SAR.json"
                RESULT_VARIABLE rc OUTPUT_VARIABLE out ERROR_VARIABLE err)
if(NOT rc EQUAL 0)
  message(FATAL_ERROR "SAR system config failed --validate (exit ${rc}):\n${out}${err}")
endif()
file(REMOVE_RECURSE "${TMP_DIR}")
file(MAKE_DIRECTORY "${TMP_DIR}")
file(READ "${CONFIG_DIR}/system/radar_0_IWR1843_SAR.json" j)
string(JSON j SET "${j}" radar_cfg "\"${CONFIG_DIR}/radar/nav_configs/1843_RadVel.cfg\"")
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
file(READ "${CONFIG_DIR}/system/front_radar_IWR1843_stress_test.json" j)
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

execute_process(COMMAND "${DRIVER}" RESULT_VARIABLE rc OUTPUT_VARIABLE out ERROR_VARIABLE err)
if(rc EQUAL 0 OR NOT err MATCHES "usage:")
  message(FATAL_ERROR "no-argument run did not print usage and fail (exit ${rc})")
endif()

message(STATUS "${n} configs validated; calibData not skipped, v1 rejection, output.dir under a file and usage checked")
