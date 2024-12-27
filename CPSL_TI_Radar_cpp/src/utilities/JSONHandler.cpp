#include "JSONHandler.hpp"

using json = nlohmann::json;

/**
 * @brief Parse a new JSON file using the nlohmann::json package
 * 
 * @param file_name the path to the .json file
 * @param print_JSON on True, prints the contents of the JSON file
 * @return json - a new json object
 */
json JSONHandler::parse_JSON(
    std::string & file_name,
    bool print_JSON)
{
    std::ifstream f(file_name);
    json data;

    if(f.is_open()){
        data = json::parse(f);
        if (print_JSON){
            std::cout << "JSONHANDLER::parse_JSON: JSON read successfully with contents: \n";
            std::cout << std::setw(4) << data << std::endl;
        }
        else{
            std::cout << "JSONHANDLER::parse_JSON: JSON read successfully\n";
        }
    }
    else{
        std::cerr << "JSONHandler::parse_JSON: Unable to open file\n";
    }
    return data;
}

/**
 * @brief Print the contents of a json file
 * 
 * @param file_name the path to a json file
 */
void JSONHandler::print_file(std::string & file_name){
    std::string line;
    std::ifstream f (file_name);
    if (f.is_open())
    {
        while ( std::getline (f,line) )
        {
        std::cout << line << '\n';
        }
        f.close();
    }

    else std::cerr << "JSONHandler::print_file: Unable to open file\n";
}

