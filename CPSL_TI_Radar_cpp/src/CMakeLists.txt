#add subdirectories (each one declares its own libraries, include directories
#and dependencies; there is no central include block)
add_subdirectory(utilities) #must be done first
add_subdirectory(CLIController)
add_subdirectory(SerialStreamer)
add_subdirectory(DCA1000)
add_subdirectory(Runners)
add_subdirectory(BoardDescriptor) #not linked into the driver yet (core-10)

#if a new library is created, give it its own target_include_directories in its
#subdirectory and add the subdirectory here (bench/ is added from the top level)

#the single target downstream projects link: CPSL_TI_Radar::driver
add_library(driver INTERFACE)
target_link_libraries(driver INTERFACE Runner)
add_library(${PKG_NAME}::driver ALIAS driver)
