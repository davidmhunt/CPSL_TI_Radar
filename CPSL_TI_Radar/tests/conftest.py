import pytest
import os

def pytest_addoption(parser):
    #add option to specify the config path to test different radar configurations
    parser.addoption(
        "--json_config",
        type=str,
        action = "store",
        default = 'radar_1.json',
        help='json config filder in the json_radar_settings folder'
    )

@pytest.fixture
def json_config_path(request):
    #get the desired file
    config_file = request.config.getoption("--json_config")

    #return the full path to the file
    return os.path.join(os.getcwd(),"json_radar_settings",config_file)