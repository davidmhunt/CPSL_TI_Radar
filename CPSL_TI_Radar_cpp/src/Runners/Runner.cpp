#include "Runner.hpp"

/**
 * @brief default contructor (leaves uninitialized)
 * 
 */
Runner::Runner():
    initialized(false),
    running_dca1000(false),
    running_serial(false),
    stop_called(true),
    system_config_reader(),
    radar_config_reader(),
    dca1000_handler(),
    cli_controller(),
    serial_streamer(),
    stop_called_mutex(),
    running_dca1000_mutex(),
    running_serial_mutex(),
    run_thread_dca1000(),
    run_thread_serial()
{}

/**
 * @brief Contructor with initialization
 * 
 * @param json_config_file_path 
 */
Runner::Runner(const std::string & json_config_file_path):
    initialized(false),
    running_dca1000(false),
    running_serial(false),
    stop_called(true),
    system_config_reader(),
    radar_config_reader(),
    dca1000_handler(),
    cli_controller(),
    serial_streamer(),
    stop_called_mutex(),
    running_dca1000_mutex(),
    running_serial_mutex(),
    run_thread_dca1000(),
    run_thread_serial()
{
    initialize(json_config_file_path);
}

Runner::~Runner(){

    //send the stop commands
    stop();
}


void Runner::initialize(const std::string & json_config_file_path){

    initialized = false;
    running_dca1000 = false;
    running_serial = false;
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
    if(radar_config_reader.initialized &&
        system_config_reader.get_dca1000_streaming_enabled()){
        dca1000_handler.initialize(system_config_reader,radar_config_reader);
    } 
    //setup the serial streamer
    if(system_config_reader.initialized &&
        system_config_reader.get_serial_streaming_enabled()){
        serial_streamer.initialize(system_config_reader);
    } 

    //setup the CLI handler
    if(dca1000_handler.initialized ||
        serial_streamer.initialized){
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

void Runner::start(){
    
    //set the stop_called variable
    stop_called = false;

    //start the DCA1000
    if (system_config_reader.get_dca1000_streaming_enabled())
    {
        start_dca1000();
    }

    //start the serial stream
    if (system_config_reader.get_serial_streaming_enabled())
    {
        start_serial();
    }
    

    //send start commands
    if(initialized){
        
        cli_controller.sendStartCommand();

    }else{
        std::cout << "attempted to start, but Runner isn't initialized" <<std::endl;
    }
}

void Runner::start_dca1000(){
    //check to make sure that dca1000 isn't already running
    std::unique_lock<std::mutex> running_unique_lock(
        running_dca1000_mutex,
        std::defer_lock
    );
    running_unique_lock.lock();
    if(running_dca1000){
        running_unique_lock.unlock();
        return;
    }
    running_unique_lock.unlock();

    if(initialized){
        //send the record start command to the DCA1000
        dca1000_handler.send_recordStart();
        running_dca1000 = true;

        //start the DCA1000 run thread
        run_thread_dca1000 = std::thread(&Runner::run_dca1000, this);
    }
}

void Runner::start_serial(){
    //check to make sure that dca1000 isn't already running
    std::unique_lock<std::mutex> running_unique_lock(
        running_serial_mutex,
        std::defer_lock
    );
    running_unique_lock.lock();
    if(running_serial){
        running_unique_lock.unlock();
        return;
    }
    running_unique_lock.unlock();

    if(initialized){
        //send the record start command to the DCA1000
        running_serial = true;

        //start the DCA1000 run thread
        run_thread_serial = std::thread(&Runner::run_serial, this);
    }
}

void Runner::stop(){
    
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
        if(run_thread_dca1000.joinable()){
            run_thread_dca1000.join();
        }
        if (run_thread_serial.joinable()){
            run_thread_serial.join();
        }
        

        std::cout << "runner sending stop commands" << std::endl;

        //stop the stop commands
        if (system_config_reader.get_dca1000_streaming_enabled())
        {
            dca1000_handler.send_recordStop();
        }
        cli_controller.sendStopCommand();
    }

    //set running_dca1000 value to false
    running_dca1000 = false;
    running_serial = false;
}

void Runner::run_dca1000(){

    std::unique_lock<std::mutex> stop_called_unique_lock(
        stop_called_mutex,
        std::defer_lock
    );

    std::unique_lock<std::mutex> running_unique_lock(
        running_dca1000_mutex,
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
    running_dca1000 = false;
    running_unique_lock.unlock();
}

void Runner::run_serial(){

    std::unique_lock<std::mutex> stop_called_unique_lock(
        stop_called_mutex,
        std::defer_lock
    );

    std::unique_lock<std::mutex> running_unique_lock(
        running_serial_mutex,
        std::defer_lock
    );

    while(true){
        //check to make sure that stop hasn't been called in a thread safe way
        stop_called_unique_lock.lock();
        if(stop_called){
            break;
        }
        stop_called_unique_lock.unlock();

        if(!serial_streamer.process_next_message()){
            //exit if the processing the next TLV packet fails
            break;
        }
    }

    running_unique_lock.lock();
    running_serial = false;
    running_unique_lock.unlock();
}

std::vector<std::vector<std::vector<std::complex<std::int16_t>>>> Runner::get_next_adc_cube(
    int timeout_ms
){  
    if (system_config_reader.get_dca1000_streaming_enabled())
    {
        std::chrono::steady_clock::time_point start_time = std::chrono::steady_clock::now();
        std::chrono::duration<double,std::milli> elapsed_time;

        std::vector<std::vector<std::vector<std::complex<std::int16_t>>>> ret_vector;

        while(!dca1000_handler.check_new_frame_available()){

            //sleep for 5 ms before checking again
            std::this_thread::sleep_for(std::chrono::milliseconds(5));

            //check to make sure that we haven't timed out
            elapsed_time = std::chrono::steady_clock::now() - start_time;

            if(std::chrono::duration_cast<std::chrono::milliseconds>(elapsed_time).count() > timeout_ms){
                std::cerr << "runner timed out waiting for next adc_cube" << std::endl;
                return std::vector<std::vector<std::vector<std::complex<std::int16_t>>>>();
            }
        }

        return dca1000_handler.get_latest_adc_cube();
    } else{
        std::vector<std::vector<std::vector<std::complex<std::int16_t>>>> empty_out;
        return empty_out;
    }
}


std::vector<std::vector<float>> Runner::get_next_tlv_detected_points(
    int timeout_ms
){  
    //define a ret_vector
    std::vector<std::vector<float>> ret_vector;

    if (system_config_reader.get_serial_streaming_enabled())
    {
        std::chrono::steady_clock::time_point start_time = std::chrono::steady_clock::now();
        std::chrono::duration<double,std::milli> elapsed_time;

        while(!serial_streamer.check_new_frame_available()){

            //sleep for 5 ms before checking again
            std::this_thread::sleep_for(std::chrono::milliseconds(5));

            //check to make sure that we haven't timed out
            elapsed_time = std::chrono::steady_clock::now() - start_time;

            if(std::chrono::duration_cast<std::chrono::milliseconds>(elapsed_time).count() > timeout_ms){
                std::cerr << "runner timed out waiting for next detected_points" << std::endl;
                return ret_vector;
            }
        }

        return serial_streamer.tlv_get_latest_detected_points();
    } else{
        return ret_vector;
    }
}

bool Runner::get_serial_streaming_enabled(void){
    return system_config_reader.get_serial_streaming_enabled();
}

bool Runner::get_dca1000_streaming_enabled(void){
    return system_config_reader.get_dca1000_streaming_enabled();
}

std::string Runner::get_radar_config_path(void) const{
    return system_config_reader.getRadarConfigPath();
}