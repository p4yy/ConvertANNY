import sys,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import engine
import win32com.client
folder=Path(__file__).parent/'speech';folder.mkdir(exist_ok=True);audio=(folder/'voice.wav').resolve()
voice=win32com.client.Dispatch('SAPI.SpVoice');stream=win32com.client.Dispatch('SAPI.SpFileStream');stream.Open(str(audio),3,False);voice.AudioOutputStream=stream
voice.Speak('The quick brown fox jumps over the lazy dog. This is a local speech recognition test.');stream.Close()
out=engine.transcribe(audio,{'Language':'English'})
text='\n'.join(Path(p).read_text(encoding='utf-8') for p in out if Path(p).suffix=='.txt')
assert 'fox' in text.lower(),text
(folder/'report.json').write_text(json.dumps({'passed':True,'transcript':text},indent=2));print(text)
