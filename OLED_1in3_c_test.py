import sys
import os
import logging
import time
import traceback
from lib.waveshare_OLED import OLED_1in3_c
from PIL import Image,ImageDraw,ImageFont
logging.basicConfig(level=logging.DEBUG)

try:
    disp = OLED_1in3_c.OLED_1in3_c()

    logging.info("\r 1.3inch OLED Module (C) ")
    # Initialize library.
    disp.Init()
    # Clear display.
    logging.info("clear display")
    disp.clear()

    # Create blank image for drawing.
    image1 = Image.new('1', (disp.width, disp.height), "WHITE")
    draw = ImageDraw.Draw(image1)
    font1 = ImageFont.truetype('pic/Font.ttc', 14) 
    font2 = ImageFont.truetype('pic/Font.ttc', 14) 
    logging.info ("***draw line")
    draw.line([(0,0),(127,0)], fill = 0)
    draw.line([(0,0),(0,63)], fill = 0)
    draw.line([(0,63),(127,63)], fill = 0)
    draw.line([(127,0),(127,63)], fill = 0)
    logging.info ("***draw text")
    draw.text((15,0), 'Satellite:', font = font1, fill = 0)
    draw.text((15,24), 'HDOP:', font = font2, fill = 0)
    image1=image1.rotate(180)
    disp.ShowImage(disp.getbuffer(image1))
    time.sleep(3)
    """ 
    logging.info ("***draw image")
    Himage2 = Image.new('1', (disp.width, disp.height), 255)  # 255: clear the frame
    bmp = Image.open(os.path.join(picdir, '1in3c.bmp'))
    Himage2.paste(bmp, (0,0))
    Himage2=Himage2.rotate(180)
    disp.ShowImage(disp.getbuffer(Himage2))
    time.sleep(3)
        disp.clear()
    """
except IOError as e:
    logging.info(e)

except KeyboardInterrupt:
    logging.info("ctrl + c:")
    disp.module_exit()
    exit()