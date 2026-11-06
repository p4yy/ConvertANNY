"""ConvertANNY document boundary detection and perspective correction."""
from __future__ import annotations
import json
from pathlib import Path
from PIL import Image,ImageOps,ImageFilter
from .model import ConversionError
from .paths import OutputPolicy,atomic_write
from .images import _open_image

LOOKS=('Clean document','Original colours','Black & white','Grayscale')


def _backends():
    import cv2
    import numpy as np
    cv2.setNumThreads(2)
    return cv2,np


def detect_document(image):
    cv2,np=_backends()
    work=image.convert('RGB');work.thumbnail((1000,1000));pixels=np.asarray(work)
    gray=cv2.cvtColor(pixels,cv2.COLOR_RGB2GRAY);blurred=cv2.GaussianBlur(gray,(5,5),0)
    edges=cv2.Canny(blurred,40,140);edges=cv2.morphologyEx(edges,cv2.MORPH_CLOSE,np.ones((5,5),np.uint8))
    contours,_=cv2.findContours(edges,cv2.RETR_LIST,cv2.CHAIN_APPROX_SIMPLE)
    area=work.width*work.height
    for contour in sorted(contours,key=cv2.contourArea,reverse=True)[:30]:
        if cv2.contourArea(contour)<area*.15:continue
        polygon=cv2.approxPolyDP(contour,.025*cv2.arcLength(contour,True),True)
        if len(polygon)!=4 or not cv2.isContourConvex(polygon):continue
        points=polygon[:,0,:].astype(float);center=points.mean(axis=0)
        points=points[np.argsort(np.arctan2(points[:,1]-center[1],points[:,0]-center[0]))]
        first=np.argmin(points.sum(axis=1));points=np.roll(points,-int(first),axis=0)
        return [[float(x/max(1,work.width-1)),float(y/max(1,work.height-1))] for x,y in points]
    return None


def straighten(image,corners,look='Clean document'):
    cv2,np=_backends()
    if look not in LOOKS:raise ConversionError('Choose a supported scan appearance')
    points=np.asarray(corners,dtype=np.float32)
    if points.shape!=(4,2) or not np.isfinite(points).all() or np.any(points<0) or np.any(points>1):
        raise ConversionError('Choose four corners inside the image')
    pixels=points*np.array([image.width-1,image.height-1],np.float32)
    if not cv2.isContourConvex(pixels.reshape((4,1,2))):raise ConversionError('The page corners must form a convex quadrilateral')
    width=round(max(np.linalg.norm(pixels[1]-pixels[0]),np.linalg.norm(pixels[2]-pixels[3])))+1
    height=round(max(np.linalg.norm(pixels[3]-pixels[0]),np.linalg.norm(pixels[2]-pixels[1])))+1
    if width<8 or height<8:raise ConversionError('The corners are too close together')
    if width*height>80_000_000:raise ConversionError('The scan output would be too large')
    target=np.array([[0,0],[width-1,0],[width-1,height-1],[0,height-1]],np.float32)
    transform=cv2.getPerspectiveTransform(pixels,target)
    corrected=cv2.warpPerspective(np.asarray(image.convert('RGB')),transform,(width,height),flags=cv2.INTER_CUBIC,borderMode=cv2.BORDER_REPLICATE)
    if look=='Original colours':return Image.fromarray(corrected)
    gray=cv2.cvtColor(corrected,cv2.COLOR_RGB2GRAY)
    if look=='Grayscale':return ImageOps.autocontrast(Image.fromarray(gray),cutoff=1)
    background=cv2.GaussianBlur(cv2.dilate(gray,np.ones((9,9),np.uint8)),(0,0),max(4,min(width,height)/40))
    illumination=np.maximum(background.astype(np.float32),1)
    if look=='Black & white':
        normalized=np.clip(gray.astype(np.float32)*245/illumination,0,255).astype(np.uint8)
        return Image.fromarray(cv2.adaptiveThreshold(normalized,255,cv2.ADAPTIVE_THRESH_GAUSSIAN_C,cv2.THRESH_BINARY,31,12))
    cleaned=np.clip(corrected.astype(np.float32)*245/illumination[:,:,None],0,255).astype(np.uint8)
    return ImageOps.autocontrast(Image.fromarray(cleaned),cutoff=1).filter(ImageFilter.UnsharpMask(radius=1.5,percent=70,threshold=3))


def scan_image(source,parameters,*,directory=None,token=None):
    source=Path(source)
    try:spec=json.loads(parameters.get('Corners') or 'null')
    except (TypeError,ValueError):spec=None
    look=parameters.get('Look') or LOOKS[0];rotation=0
    corners=spec
    if isinstance(spec,dict):corners=spec.get('corners');look=spec.get('look') or look;rotation=int(spec.get('rotate') or 0)
    if look not in LOOKS:look=LOOKS[0]
    if rotation%90:raise ConversionError('Scan rotation must use quarter turns')
    if token:token.check()
    image=_open_image(source)
    if corners is None:corners=detect_document(image) or [[0,0],[1,0],[1,1],[0,1]]
    result=straighten(image,corners,look)
    if rotation:result=result.rotate(-rotation,expand=True)
    extension='png' if look=='Black & white' or source.suffix.lower() in ('.png','.bmp','.gif','.svg','.ico') else 'jpg'
    destination=OutputPolicy(directory=Path(directory) if directory else None,suffix=' scanned').destination(source,extension)
    options={'format':'PNG'} if extension=='png' else {'format':'JPEG','quality':92,'optimize':True}
    return atomic_write(destination,lambda temporary:result.save(temporary,**options),token)
