from gtts import gTTS
import io
tts = gTTS(text='Hello how are you', lang='en', slow=False)
buf = io.BytesIO()
tts.write_to_fp(buf)
print('gTTS works! Size:', buf.tell(), 'bytes')