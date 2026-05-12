import pyttsx3

engine = pyttsx3.init()  

text = "helloooo sreeejaaa how are you? "

engine.say(text) #queue text for speeking 

engine.runAndWait() #plays generated voice