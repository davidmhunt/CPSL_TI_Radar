#include "JSONHandler.hpp"

using json = nlohmann::json;

json JSONHandler::parse_JSON(std::string & file_name, bool print_JSON){
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

