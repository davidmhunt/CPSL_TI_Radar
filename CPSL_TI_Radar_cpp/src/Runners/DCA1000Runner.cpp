#include "DCA1000Runner.hpp"

/**
 * @brief default contructor (leaves uninitialized)
 * 
 */
DCA1000Runner::DCA1000Runner():
    initialized(false),
    running(false),
    stop_called(true),
    system_config_reader(),
    radar_config_reader(),
    dca1000_handler(),
    cli_controller(),
    stop_called_mutex(),
    running_mutex(),
    run_thread()
{}

/**
 * @brief Contructor with initialization
 * 
 * @param json_config_file_path 
 */
DCA1000Runner::DCA1000Runner(const std::string & json_config_file_path):
    initialized(false),
    running(false),
    stop_called(true),
    system_config_reader(),
    radar_config_reader(),
    dca1000_handler(),
    cli_controller(),
    stop_called_mutex(),
    running_mutex(),
    run_thread()
{
    initialize(json_config_file_path);
}

DCA1000Runner::~DCA1000Runner(){

    //send the stop commands
    stop();
}


void DCA1000Runner::initialize(const std::string & json_config_file_path){

    initialized = false;
    running = false;
    stop_called = false;

    //initialize the system config reader
    system_config_reader = SystemConfigReader(json_config_file_path);

    //initialize the radar config reader
    if(system_config_reader.initialized){
        radar_config_reader.initialize(system_config_reader.getRadarConfigPath());
    } else{
        return;
    }

    //setup the DCA1000 handler
    if(radar_config_reader.initialized){
        dca1000_handler.initialize(system_config_reader,radar_config_reader);
    } else{
        return;
    }

    //setup the CLI handler
    if(dca1000_handler.initialized){
        cli_controller.initialize(system_config_reader);
    } else{
        return;
    }

    if (cli_controller.initialized){
        cli_controller.send_config_to_IWR();
        initialized = true;
    }else{
        initialized = false;
    }
}

void DCA1000Runner::start(){

    //check to make sure that not already running
    std::unique_lock<std::mutex> running_unique_lock(
        running_mutex,
        std::defer_lock
    );
    running_unique_lock.lock();
    if(running){
        running_unique_lock.unlock();
        return;
    }
    running_unique_lock.unlock();

    //send start commands
    if(initialized){
        dca1000_handler.send_recordStart();
        cli_controller.sendStartCommand();

        //start the run loop
        stop_called = false;
        running = true;

        run_thread = std::thread(&DCA1000Runner::run, this);
    }else{
        std::cout << "attempted to start, but DCA1000Runner isn't initialized" <<std::endl;
    }
}

void DCA1000Runner::stop(){
    
    //set the stop called flag to true
    std::unique_lock<std::mutex> stop_called_unique_lock(
        stop_called_mutex,
        std::defer_lock
    );
    stop_called_unique_lock.lock();
    stop_called = true;
    stop_called_unique_lock.unlock();

    if(initialized){
        //join the run thread
        if(run_thread.joinable()){
            run_thread.join();
        }

        std::cout << "runner sending stop commands" << std::endl;

        //stop the stop commands
        dca1000_handler.send_recordStop();
        cli_controller.sendStartCommand();
    }

    //set running value to false
    running = false;
}

void DCA1000Runner::run(){

    std::unique_lock<std::mutex> stop_called_unique_lock(
        stop_called_mutex,
        std::defer_lock
    );

    std::unique_lock<std::mutex> running_unique_lock(
        running_mutex,
        std::defer_lock
    );

    while(true){
        //check to make sure that stop hasn't been called in a thread safe way
        stop_called_unique_lock.lock();
        if(stop_called){
            break;
        }
        stop_called_unique_lock.unlock();

        if(!dca1000_handler.process_next_packet()){
            //exit if the processing the next packet fails
            break;
        }
    }

    running_unique_lock.lock();
    running = false;
    running_unique_lock.unlock();
}

std::vector<std::vector<std::vector<std::complex<std::int16_t>>>> DCA1000Runner::get_next_frame(
    int timeout_ms
){
    std::chrono::steady_clock::time_point start_time = std::chrono::steady_clock::now();
    std::chrono::duration<double,std::milli> elapsed_time;

    std::vector<std::vector<std::vector<std::complex<std::int16_t>>>> ret_vector;

    while(!dca1000_handler.check_new_frame_available()){

        //sleep for 5 ms before checking again
        std::this_thread::sleep_for(std::chrono::milliseconds(5));

        //check to make sure that we haven't timed out
        elapsed_time = std::chrono::steady_clock::now() - start_time;

        if(std::chrono::duration_cast<std::chrono::milliseconds>(elapsed_time).count() > timeout_ms){
            std::cerr << "runner timed out waiting for next frame" << std::endl;
            return std::vector<std::vector<std::vector<std::complex<std::int16_t>>>>();
        }
    }

    return dca1000_handler.get_latest_adc_cube();
}