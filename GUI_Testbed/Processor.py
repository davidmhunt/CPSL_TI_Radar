from multiprocessing import Queue, connection
import serial
import time
import json
import numpy as np
import os
import sys

from _Background_Process import _BackgroundProcess

class Processor(_BackgroundProcess):
    def __init__(self, process_name, conn: connection.Connection, queue: Queue = None, config_file_path='config_RADAR.json'):
        super().__init__(process_name, conn, queue, config_file_path)