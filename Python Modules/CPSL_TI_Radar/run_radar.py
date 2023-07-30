from CPSL_TI_Radar.Radar import Radar

#create the controller object
radar = Radar("CPSL_TI_Radar_settings.json")
radar.run(timeout=20)