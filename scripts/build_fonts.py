"""Bake the approved Inter variable source into stable desktop font faces."""
from pathlib import Path
from fontTools.ttLib import TTFont
from fontTools.varLib.instancer import instantiateVariableFont

folder = Path(__file__).resolve().parents[1] / 'src/assets/fonts'
for weight, style in ((400, 'Regular'), (500, 'Medium'), (600, 'SemiBold'), (700, 'Bold')):
    source = TTFont(folder / 'InterVariable.ttf')
    axes = {axis.axisTag: axis.defaultValue for axis in source['fvar'].axes}
    axes['wght'] = weight
    font = instantiateVariableFont(source, axes, inplace=True)
    names = {1: 'ConvertANNY UI', 2: style, 3: f'ConvertANNYUI-{style}',
             4: f'ConvertANNY UI {style}', 6: f'ConvertANNYUI-{style}',
             16: 'ConvertANNY UI', 17: style}
    for entry in list(font['name'].names):
        if entry.nameID in names:
            font['name'].setName(names[entry.nameID], entry.nameID, entry.platformID,
                                 entry.platEncID, entry.langID)
    font.save(folder / f'ConvertANNYInter-{style}.ttf')
    font.close()
