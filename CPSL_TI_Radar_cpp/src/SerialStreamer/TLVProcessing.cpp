#include "TLVProcessing.hpp"

/**
 * @brief Construct a new TLVDetectedPoints::TLVDetectedPoints object
 * 
 */
TLVDetectedPoints::TLVDetectedPoints():
    valid_data(false),
    detected_points(0,std::vector<float>(0,0)){}

TLVDetectedPoints::TLVDetectedPoints(const TLVDetectedPoints & rhs):
    valid_data(rhs.valid_data),
    detected_points(rhs.detected_points){}

TLVDetectedPoints & TLVDetectedPoints::operator=(const TLVDetectedPoints & rhs){
    if(this!= & rhs){

        valid_data = rhs.valid_data;
        detected_points = rhs.detected_points;
    }

    return *this;
}

TLVDetectedPoints::~TLVDetectedPoints(){}

void TLVDetectedPoints::process(
    std::vector<uint8_t> & tlv_raw_data_bytes
){
    //convert the byte data into float data
    std::vector<float> float_data = bytes_to_floats(
        tlv_raw_data_bytes
    );

    //compute the number of rows and columns
    size_t num_rows = float_data.size() / 4;
    size_t num_cols = 4;

    //initialize the detect_points vector
    detected_points = std::vector<std::vector<float>>(
        num_rows,
        std::vector<float>(num_cols,0.0)
    );

    size_t idx = 0;
    for (size_t r = 0; r < num_rows; r++)
    {
        for (size_t c = 0; c < num_cols; c++)
        {
            detected_points[r][c] = float_data[idx];
            idx++;
        }
    }
    
    valid_data = true;
    return;
}

std::vector<float> TLVDetectedPoints::bytes_to_floats(
    std::vector<uint8_t> & bytes
){

    std::vector<float> out_vector(bytes.size()/4,0.0);

    for (size_t i = 0; i < bytes.size(); i += 4) {
        // Extract a 4-byte segment as a uint32_t
        uint32_t raw_value;
        std::memcpy(&raw_value, &bytes[i], sizeof(uint32_t));

        // Convert from little-endian to host byte order
        uint32_t host_value = le32toh(raw_value);

        // Reinterpret the uint32_t value as a float
        float float_value;
        std::memcpy(&float_value, &host_value, sizeof(float));

        // Append the float to the result vector
        out_vector[i/4] = float_value;
    }
    
    return out_vector;
}