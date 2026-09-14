import whisper
print('Downloading large model (2.9GB)... this will take a few minutes')
model = whisper.load_model('large')
print('Large model ready!')