//C standard libraries
#include <iostream>
#include <cstdlib>
#include <string>
#include <vector>
#include <fstream>
#include <sstream>
#include <unistd.h>

//JSON handling
#include "JSONHandler.hpp"
#include "SystemConfigReader.hpp"
#include "CLIController.hpp"
#include "DCA1000Commands.hpp"
#include "DCA1000Handler.hpp"

using json = nlohmann::json;

int main(int, char**){

    std::string config_file = "/home/cpsl/Documents/CPSL_TI_Radar/CPSL_TI_Radar_cpp/configs/radar_1.json";

    SystemConfigReader config_reader = SystemConfigReader(config_file);

    std::cout << std::endl << "Radar Config Path: " << config_reader.getRadarConfigPath() << std::endl;
    std::cout << std::endl << "CLI Port: " << config_reader.getRadarCliPort() << std::endl;
    
    //setup the DCA1000
    DCA1000Handler dca1000_handler(config_reader);
    
    float fpga_version = dca1000_handler.send_readFPGAVersion();

    std::cout << "FPGA version: " << fpga_version << std::endl;

    bool start = dca1000_handler.send_recordStart();
    std::cout << "Started: " << start << std::endl;

    //send a configuration to the radar board
    CLIController cli_controller(config_file);
    cli_controller.run();


    // Read the configuration file and extract relevant parameters
    std::ifstream cfgFile(config_reader.getRadarConfigPath());
    if (!cfgFile.is_open()) {
        std::cerr << "Failed to open configuration file: " << config_reader.getRadarConfigPath() << std::endl;
        return 1;
    }

    int numLoopsPerFrame = 0;
    int numChirpsPerLoop = 0;
    int numSamplesPerChirp = 0;
    int numBytesPerSample = 2; // As found in mmwave Radar Device ADC Raw Data Capture Guide
    int numAntennas = 4;

    // UDP Packet info, found in the DCA1000 Software User Guide

    int sequenceNumSize = 4;
    int byteCountSize = 6;
    int packetDataSize = 1462; //in Bytes
    int packetSize = sequenceNumSize + byteCountSize + packetDataSize;

    std::string line;
    while (std::getline(cfgFile, line)) {

        // The # of loops/frame is the 3rd number of the frameCfg command
        if (line.find("frameCfg") != std::string::npos) {
            std::istringstream iss(line);
            std::string dummy;
            iss >> dummy >> dummy >> dummy >> numLoopsPerFrame;

        // The # of chirps/loop is the 2nd number - 1st number + 1 of frameCfg (Chirp end index - start index + 1)
        } else if (line.find("chirpCfg") != std::string::npos) {
            std::istringstream iss(line);
            std::string dummy;
            int startIdx, endIdx;
            iss >> dummy >> startIdx >> endIdx;
            numChirpsPerLoop = endIdx - startIdx + 1;

        // The # of samples/chirp is the 10th number of profileCfg
        } else if (line.find("profileCfg") != std::string::npos) {
            std::istringstream iss(line);
            std::string dummy;
            for (int i = 0; i < 10; ++i) {
                iss >> dummy;
            }
            iss >> numSamplesPerChirp;
        }
    }

    cfgFile.close();

    // Calculate bytes/frame
    int bytesPerFrame = numBytesPerSample * numAntennas * numSamplesPerChirp * numChirpsPerLoop * numLoopsPerFrame;
    int numChirpsPerFrame = numChirpsPerLoop * numLoopsPerFrame;

    // Create a 3D vector to store the received data (the order is a little messed up)
    std::vector<std::vector<std::vector<uint16_t>>> data(numSamplesPerChirp, std::vector<std::vector<uint16_t>>(numChirpsPerFrame, std::vector<uint16_t>(numAntennas)));

    // Variables to keep track of sample, chirp, and rx numbers
    int sampleNum = 0;
    int chirpNum = 0;
    int rx = 0;

    // Keep track of packet sequence numbers
    static uint32_t expectedSequenceNum = 0;
    int numSamplesPerPacket = packetDataSize / numBytesPerSample;


    // Receive packets and store them in the vector
    while (true) {
        std::vector<uint8_t> buffer(1472);

        if (!dca1000_handler.receiveData(buffer)) {
            std::cerr << "Failed to receive packet" << std::endl;
            continue;
        }

        std::cout << sizeof(buffer);

        // Extract sequence number and byte count from the packet
        uint32_t sequenceNum = le32toh(*(uint32_t*)&buffer[0]);
        uint64_t byteCount = (static_cast<uint64_t>(buffer[4]) << 40) |
                     (static_cast<uint64_t>(buffer[5]) << 32) |
                     (static_cast<uint64_t>(buffer[6]) << 24) |
                     (static_cast<uint64_t>(buffer[7]) << 16) |
                     (static_cast<uint64_t>(buffer[8]) << 8)  |
                     static_cast<uint64_t>(buffer[9]);

        // Check if the sequence number is in order
        std::cout << sequenceNum;

        if (sequenceNum == expectedSequenceNum) {
            for (int i = sequenceNumSize + byteCountSize; i < packetSize; i = i + numBytesPerSample) {
                // Gets the next two bytes from the packet (one sample) and converts to big endian
                uint16_t currentData = le16toh(*(uint16_t*)&buffer[i]);
                // Logic for putting samples in the array: fills up rx first, then samples, then chirps
                data[sampleNum][chirpNum][rx] = currentData;
                if ((rx + 1) == 4) {
                    rx = 0;
                    if ((sampleNum + 1) == numSamplesPerChirp) {
                        sampleNum = 0;
                        if ((chirpNum + 1) == numChirpsPerFrame) {
                            chirpNum = 0;
                            // Vector is filled, write it to external storage and clear it
                            std::ofstream outputFile("output.bin", std::ios::binary);
                            // Order is wonky but follows rx, samples, chirps
                            for (int b = 0; b < numChirpsPerFrame; ++b) {
                                for (int a = 0; a < numSamplesPerChirp; ++a) {
                                    for (int c = 0; c < numAntennas; ++c) {
                                    outputFile.write(reinterpret_cast<const char*>(&data[a][b][c]), sizeof(uint16_t));
                                    }
                                }
                            }
                            outputFile.close();

                            // Clear the vector
                            data.clear();
                            data.resize(numSamplesPerChirp, std::vector<std::vector<uint16_t>>(numChirpsPerFrame, std::vector<uint16_t>(numAntennas)));
                        }
                        else {
                            ++chirpNum;
                        }
                    }
                    else {
                        ++sampleNum;
                    }
                }
                else {
                    ++rx;
                }
            }
            ++expectedSequenceNum;
        }
        else {
            for (int i = sequenceNumSize + byteCountSize; i < packetSize; i = i + numBytesPerSample) {
                // Fill with 0s if dropped packet
                uint16_t currentData = 0;
                data[sampleNum][chirpNum][rx] = currentData;
                if ((rx + 1) == 4) {
                    rx = 0;
                    if ((sampleNum + 1) == numSamplesPerChirp) {
                        sampleNum = 0;
                        if ((chirpNum + 1) == numChirpsPerFrame) {
                            chirpNum = 0;

                            // Vector is filled, write it to external storage and clear it, same logic as above
                            std::ofstream outputFile("output.bin", std::ios::binary);
                            for (int b = 0; b < numChirpsPerFrame; ++b) {
                                for (int a = 0; a < numSamplesPerChirp; ++a) {
                                    for (int c = 0; c < numAntennas; ++c) {
                                    outputFile.write(reinterpret_cast<const char*>(&data[a][b][c]), sizeof(uint16_t));
                                    }
                                }
                            }
                            outputFile.close();

                            // Clear the vector
                            data.clear();
                            data.resize(numSamplesPerChirp, std::vector<std::vector<uint16_t>>(numChirpsPerFrame, std::vector<uint16_t>(numAntennas)));
                        }
                        else {
                            ++chirpNum;
                        }
                    }
                    else {
                        ++sampleNum;
                    }
                }
                else {
                    ++rx;
                }
            }
        expectedSequenceNum = sequenceNum;
        }
    }
    return 0;
}
