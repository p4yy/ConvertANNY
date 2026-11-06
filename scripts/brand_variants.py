from pathlib import Path
from fontTools.ttLib import TTFont
from fontTools.varLib.instancer import instantiateVariableFont
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from PIL import Image
root=Path(__file__).resolve().parents[1];brand=root/'src/assets/brand'
font=instantiateVariableFont(TTFont(root/'src/assets/fonts/InterVariable.ttf'),{'wght':700,'opsz':32},inplace=False)
glyphs=font.getGlyphSet();cmap=font.getBestCmap();scale=165/font['head'].unitsPerEm
paths=[];x=470
for char in 'ConvertANNY':
 name=cmap[ord(char)];pen=SVGPathPen(glyphs);glyphs[name].draw(TransformPen(pen,(scale,0,0,-scale,x,263)));paths.append(pen.getCommands());x+=glyphs[name].width*scale-5
icon=(brand/'ConvertANNY.svg').read_text();inner=icon[icon.index('<defs>'):icon.rindex('</svg>')]
for fill,name in [('#ffffff','dark-background'),('#111111','light-background')]:
 (brand/f'ConvertANNY-horizontal-{name}.svg').write_text(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {int(x+20)} 410">'+inner+f'<path fill="{fill}" d="'+''.join(paths)+'"/></svg>')
for fill,cut,name in [('#ffffff','#000000','light'),('#111111','#ffffff','dark')]:
 (brand/f'glyph-{name}.svg').write_text(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 410 410"><path fill="{fill}" opacity=".6" d="M68 152h175v190H68z"/><path fill="{fill}" d="M119 58h142l81 80v169H119z"/><path fill="none" stroke="{cut}" stroke-width="18" stroke-linecap="round" stroke-linejoin="round" d="M170 211q7-30 41-30h79m-28-23 29 23-29 23M291 222q-6 28-40 28h-79m29-24-30 24 30 22"/></svg>')
store=root/'packaging/StoreAssets';store.mkdir(exist_ok=True)
source=Image.open(root/'branding/icons/png/ConvertANNY_512.png').convert('RGBA')
for name,size,mark in [('Square44x44Logo',44,40),('Square150x150Logo',150,100),('StoreLogo',50,46)]:
 for factor in [1,1.25,1.5,2,4]:
  n=round(size*factor);m=round(mark*factor);im=Image.new('RGBA',(n,n));small=source.resize((m,m),Image.Resampling.LANCZOS);im.alpha_composite(small,((n-m)//2,(n-m)//2));im.save(store/f'{name}.scale-{round(factor*100)}.png')
for n in [16,20,24,32,48,256]:source.resize((n,n),Image.Resampling.LANCZOS).save(store/f'Square44x44Logo.targetsize-{n}_altform-unplated.png')
print('Outlined wordmarks, monochrome glyphs and Store scale variants exported')
