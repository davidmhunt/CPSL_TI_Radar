class _MessageTypes:
    #largest hex value corresponding to a message
    _LARGEST_MESSAGE_VALUE = 0x0D

    #init messages
    INIT_SUCCESS = 0x00
    INIT_FAIL = 0x01

    #exit messages
    EXIT = 0x02

    #print messages
    PRINT_TO_TERMINAL = 0x03
    PRINT_CLEAR_TERMINAL = 0x04

    #command executed - returned when a
    #background process completes a command
    COMMAND_EXECUTED = 0x05

    #CLI Controller TI radar operation messages
    START_SENSOR = 0x06
    STOP_SENSOR = 0x07
    SEND_CONFIG = 0x08
    LOAD_NEW_CONFIG = 0x09 #also supported by Processor

    #Streamer/Processor control messages
    START_STREAMING = 0x0A
    STOP_STREAMING = 0x0B
    
    #New Data Available
    NEW_DATA = 0x0C

    #Other Errors
    ERROR_RADAR = 0x0D

class _Message:


    def __init__(self,type,value = None):
        
        #check message type
        self.type = type
        if type > _MessageTypes._LARGEST_MESSAGE_VALUE:
            raise InvalidMessageType(type)
        pass

        #set message value
        self.value = value

class InvalidMessageType(Exception):

    def __init__(self,message_type):
        self.message = "{} is not a valid message type".format(message_type)
        super().__init__(message_type)