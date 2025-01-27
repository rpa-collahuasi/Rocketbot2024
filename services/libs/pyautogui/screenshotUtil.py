# Screenshot-related features of PyAutoGUI

"""
So, apparently Pillow support on Ubuntu 64-bit has several additional steps since it doesn't have JPEG/PNG support out of the box. Description here:

https://stackoverflow.com/questions/7648200/pip-install-pil-e-tickets-1-no-jpeg-png-support
http://ubuntuforums.org/showthread.php?t=1751455
"""

# PyScreeze
# by Al Sweigart
# https://github.com/asweigart/pyscreeze
# BSD license

"""
So, apparently Pillow support on Ubuntu 64-bit has several additional steps since it doesn't have JPEG/PNG support out of the box. Description here:

https://stackoverflow.com/questions/7648200/pip-install-pil-e-tickets-1-no-jpeg-png-support
http://ubuntuforums.org/showthread.php?t=1751455
"""

__version__ = '0.1.14'

import datetime
import os
import subprocess
import sys
import time
import errno
try:
    from PIL import Image
    from PIL import ImageOps
except ImportError:
    pass

try:
    import cv2
    import numpy
    useOpenCV = True
    RUNNING_CV_2 = cv2.__version__[0] < '3'
except ImportError:
    useOpenCV = False

RUNNING_PYTHON_2 = sys.version_info[0] == 2
if useOpenCV:
    if RUNNING_CV_2:
        LOAD_COLOR = cv2.CV_LOAD_IMAGE_COLOR
        LOAD_GRAYSCALE = cv2.CV_LOAD_IMAGE_GRAYSCALE
    else:
        LOAD_COLOR = cv2.IMREAD_COLOR
        LOAD_GRAYSCALE = cv2.IMREAD_GRAYSCALE


RAISE_IF_NOT_FOUND = False
GRAYSCALE_DEFAULT = False

scrotExists = False
try:
    if sys.platform not in ('java', 'darwin', 'win32'):
        whichProc = subprocess.Popen(
            ['which', 'scrot'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        scrotExists = whichProc.wait() == 0
except OSError as ex:
    if ex.errno == errno.ENOENT:
        # if there is no "which" program to find scrot, then assume there
        # is no scrot.
        pass
    else:
        raise


if sys.platform == 'win32':
    from ctypes import windll


class ImageNotFoundException(Exception):
    pass


def _load_cv2(img, grayscale=None):
    # load images if given filename, or convert as needed to opencv
    # Alpha layer just causes failures at this point, so flatten to RGB.
    # RGBA: load with -1 * cv2.CV_LOAD_IMAGE_COLOR to preserve alpha
    # to matchTemplate, need template and image to be the same wrt having alpha
    try:
        if grayscale is None:
            grayscale = GRAYSCALE_DEFAULT
        if isinstance(img, str):
            # The function imread loads an image from the specified file and
            # returns it. If the image cannot be read (because of missing
            # file, improper permissions, unsupported or invalid format),
            # the function returns an empty matrix
            # http://docs.opencv.org/3.0-beta/modules/imgcodecs/doc/reading_and_writing_images.html
            if grayscale:
                img_cv = cv2.imread(img, LOAD_GRAYSCALE)
            else:
                img_cv = cv2.imread(img, LOAD_COLOR)
            if img_cv is None:
                raise IOError("Failed to read %s because file is missing, "
                            "has improper permissions, or is an "
                            "unsupported or invalid format" % img)
        elif isinstance(img, numpy.ndarray):
            # don't try to convert an already-gray image to gray
            if grayscale and len(img.shape) == 3:  # and img.shape[2] == 3:
                img_cv = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        elif hasattr(img, 'convert'):
            # assume its a PIL.Image, convert to cv format
            img_array = numpy.array(img.convert('RGB'))
            img_cv = img_array[:, :, ::-1].copy()  # -1 does RGB -> BGR
            if grayscale:
                img_cv = cv2.cvtColor(img_cv, cv2.COLOR_BGR2GRAY)
        else:
            raise TypeError(
                'expected an image filename, OpenCV numpy array, or PIL image')
        return img_cv
    except Exception as e:
        print(e)


def _locateAll_opencv(needleImage, haystackImage, grayscale=None, limit=10000, region=None, step=1,
                      confidence=0.8):
    """ faster but more memory-intensive than pure python
        step 2 skips every other row and column = ~3x faster but prone to miss;
            to compensate, the algorithm automatically reduces the confidence
            threshold by 5% (which helps but will not avoid all misses).
        limitations:
          - OpenCV 3.x & python 3.x not tested
          - RGBA images are treated as RBG (ignores alpha channel)
    """
    if grayscale is None:
        grayscale = GRAYSCALE_DEFAULT

    confidence = float(confidence)
    needleImage = _load_cv2(needleImage, grayscale)
    needleHeight, needleWidth = needleImage.shape[:2]
    haystackImage = _load_cv2(haystackImage, grayscale)
    if region:
        haystackImage = haystackImage[region[1]:region[1]+region[3],
                                      region[0]:region[0]+region[2]]
    else:
        region = (0, 0)  # full image; these values used in the yield statement
    if (haystackImage.shape[0] < needleImage.shape[0] or
            haystackImage.shape[1] < needleImage.shape[1]):
        # avoid semi-cryptic OpenCV error below if bad size
        raise ValueError(
            'needle dimension(s) exceed the haystack image or region dimensions')

    if step == 2:
        confidence *= 0.95
        needleImage = needleImage[::step, ::step]
        haystackImage = haystackImage[::step, ::step]
    else:
        step = 1
    # get all matches at once, credit: https://stackoverflow.com/questions/7670112/finding-a-subimage-inside-a-numpy-image/9253805#9253805
    result = cv2.matchTemplate(
        haystackImage, needleImage, cv2.TM_CCOEFF_NORMED)
    match_indices = numpy.arange(result.size)[(result > confidence).flatten()]
    matches = numpy.unravel_index(match_indices[:limit], result.shape)

    if len(matches[0]) == 0 and RAISE_IF_NOT_FOUND:
        raise ImageNotFoundException(
            'Could not locate the image (highest confidence = %.3f)' % result.max())

    # use a generator for API consistency:
    matchx = matches[1] * step + region[0]  # vectorized
    matchy = matches[0] * step + region[1]
    for x, y in zip(matchx, matchy):
        yield (x, y, needleWidth, needleHeight)


def _locateAll_python(needleImage, haystackImage, grayscale=None, limit=None, region=None, step=1, confidence = None):
    # setup all the arguments
    if grayscale is None:
        grayscale = GRAYSCALE_DEFAULT

    needleFileObj = None
    if isinstance(needleImage, str):
        # 'image' is a filename, load the Image object
        needleFileObj = open(needleImage, 'rb')
        needleImage = Image.open(needleFileObj)

    haystackFileObj = None
    if isinstance(haystackImage, str):
        # 'image' is a filename, load the Image object
        haystackFileObj = open(haystackImage, 'rb')
        haystackImage = Image.open(haystackFileObj)

    if region is not None:
        haystackImage = haystackImage.crop(
            (region[0], region[1], region[0] + region[2], region[1] + region[3]))
    else:
        # set to 0 because the code always accounts for a region
        region = (0, 0)

    if grayscale:  # if grayscale mode is on, convert the needle and haystack images to grayscale
        needleImage = ImageOps.grayscale(needleImage)
        haystackImage = ImageOps.grayscale(haystackImage)
    else:
        # if not using grayscale, make sure we are comparing RGB images, not RGBA images.
        if needleImage.mode == 'RGBA':
            needleImage = needleImage.convert('RGB')
        if haystackImage.mode == 'RGBA':
            haystackImage = haystackImage.convert('RGB')

    # setup some constants we'll be using in this function
    needleWidth, needleHeight = needleImage.size
    haystackWidth, haystackHeight = haystackImage.size

    needleImageData = tuple(needleImage.getdata())
    haystackImageData = tuple(haystackImage.getdata())

    # LEFT OFF - check this
    needleImageRows = [
        needleImageData[y * needleWidth:(y+1) * needleWidth] for y in range(needleHeight)]
    needleImageFirstRow = needleImageRows[0]

    assert len(needleImageFirstRow) == needleWidth, 'For some reason, the calculated width of first row of the needle image is not the same as the width of the image.'
    assert [len(row) for row in needleImageRows] == [needleWidth] * \
        needleHeight, 'For some reason, the needleImageRows aren\'t the same size as the original image.'

    numMatchesFound = 0

    # NOTE: After running tests/benchmarks.py on the following code, it seem that having a step
    # value greater than 1 does not give *any* significant performance improvements.
    # Since using a step higher than 1 makes for less accurate matches, it will be
    # set to 1.
    # hard-code step as 1 until a way to improve it can be figured out.
    step = 1

    if step == 1:
        firstFindFunc = _kmp
    else:
        firstFindFunc = _steppingFind

    for y in range(haystackHeight):  # start at the leftmost column
        for matchx in firstFindFunc(needleImageFirstRow, haystackImageData[y * haystackWidth:(y+1) * haystackWidth], step):
            foundMatch = True
            for searchy in range(1, needleHeight, step):
                haystackStart = (searchy + y) * haystackWidth + matchx
                if needleImageData[searchy * needleWidth:(searchy+1) * needleWidth] != haystackImageData[haystackStart:haystackStart + needleWidth]:
                    foundMatch = False
                    break
            if foundMatch:
                # Match found, report the x, y, width, height of where the matching region is in haystack.
                numMatchesFound += 1
                yield (matchx + region[0], y + region[1], needleWidth, needleHeight)
                if limit is not None and numMatchesFound >= limit:
                    # Limit has been reached. Close file handles.
                    if needleFileObj is not None:
                        needleFileObj.close()
                    if haystackFileObj is not None:
                        haystackFileObj.close()
                    raise StopIteration()

    # There was no limit or the limit wasn't reached, but close the file handles anyway.
    if needleFileObj is not None:
        needleFileObj.close()
    if haystackFileObj is not None:
        haystackFileObj.close()

    if RAISE_IF_NOT_FOUND and numMatchesFound == 0:
        raise ImageNotFoundException('Could not locate the image.')


def locate(needleImage, haystackImage, **kwargs):
    # Note: The gymnastics in this function is because we want to make sure to exhaust the iterator so that the needle and haystack files are closed in locateAll.
    kwargs['limit'] = 1
    points = tuple(locateAll(needleImage, haystackImage, **kwargs))
    if len(points) > 0:
        return points[0]
    else:
        return None


def locateOnScreen(image, minSearchTime=0, **kwargs):
    """minSearchTime - amount of time in seconds to repeat taking
    screenshots and trying to locate a match.  The default of 0 performs
    a single search.
    """
    start = time.time()
    while True:
        try:
            # the locateAll() function must handle cropping to return accurate coordinates, so don't pass a region here.
            screenshotIm = screenshot(imageFilename="tmp.png", region=None)
            retVal = locate(image, "tmp.png", **kwargs)
            try:
                screenshotIm.fp.close()
            except AttributeError:
                # Screenshots on Windows won't have an fp since they came from
                # ImageGrab, not a file. Screenshots on Linux will have fp set
                # to None since the file has been unlinked
                pass
            if retVal or time.time() - start > minSearchTime:
                return retVal
        except ImageNotFoundException:
            if time.time() - start > minSearchTime:
                raise


def locateAllOnScreen(image, **kwargs):
    # the locateAll() function must handle cropping to return accurate coordinates, so don't pass a region here.
    screenshotIm = screenshot(imageFilename="tmp.png",region=None)
    retVal = locateAll(image, screenshotIm, **kwargs)
    try:
        screenshotIm.fp.close()
    except AttributeError:
        # Screenshots on Windows won't have an fp since they came from
        # ImageGrab, not a file. Screenshots on Linux will have fp set
        # to None since the file has been unlinked
        pass
    return retVal


def locateCenterOnScreen(image, **kwargs):
    coords = locateOnScreen(image, **kwargs)
    if coords is None:
        return None
    else:
        return center(coords)


def showRegionOnScreen(region, outlineColor='red', filename='_showRegionOnScreen.png'):
    # this is the only function that needs this, and it's rarely called
    from PIL import ImageDraw
    screenshotIm = screenshot()
    draw = ImageDraw.Draw(screenshotIm)
    # convert from (left, top, right, bottom) to (left, top, width, height)
    region = (region[0], region[1], region[2] +
              region[0], region[3] + region[1])
    draw.rectangle(region, outline=outlineColor)
    screenshotIm.save(filename)


def _screenshot_win32(imageFilename=None, region=None):
    try:
        im = ImageGrab.grab()
    except NameError:
        raise ImportError(
            'Pillow module must be installed to use screenshot functions on Windows.')
    if region is not None:
        assert len(region) == 4, 'region argument must be a tuple of four ints'
        region = [int(x) for x in region]
        im = im.crop((region[0], region[1], region[2] +
                      region[0], region[3] + region[1]))
    if imageFilename is not None:
        im.save(imageFilename)
    return im


def _screenshot_osx(imageFilename=None, region=None):
    if imageFilename is None:
        tmpFilename = 'screenshot%s.png' % (
            datetime.datetime.now().strftime('%Y-%m%d_%H-%M-%S-%f'))
    else:
        tmpFilename = imageFilename
    subprocess.call(['screencapture', '-x', tmpFilename])
    im = Image.open(tmpFilename)

    if region is not None:
        assert len(region) == 4, 'region argument must be a tuple of four ints'
        region = [int(x) for x in region]
        im = im.crop((region[0], region[1], region[2] +
                      region[0], region[3] + region[1]))
    else:
        # force loading before unlinking, Image.open() is lazy
        im.load()

    if imageFilename is None:
        os.unlink(tmpFilename)
    return im


def _screenshot_linux(imageFilename=None, region=None):
    if not scrotExists:
        raise NotImplementedError(
            '"scrot" must be installed to use screenshot functions in Linux. Run: sudo apt-get install scrot')
    if imageFilename is None:
        tmpFilename = '.screenshot%s.png' % (
            datetime.datetime.now().strftime('%Y-%m%d_%H-%M-%S-%f'))
    else:
        tmpFilename = imageFilename
    if scrotExists:
        subprocess.call(['scrot', tmpFilename])
        im = Image.open(tmpFilename)

        if region is not None:
            assert len(
                region) == 4, 'region argument must be a tuple of four ints'
            region = [int(x) for x in region]
            im = im.crop((region[0], region[1], region[2] +
                          region[0], region[3] + region[1]))
        else:
            # force loading before unlinking, Image.open() is lazy
            im.load()

        if imageFilename is None:
            os.unlink(tmpFilename)
        return im
    else:
        raise Exception(
            'The scrot program must be installed to take a screenshot with PyScreeze on Linux. Run: sudo apt-get install scrot')


# Knuth-Morris-Pratt search algorithm implementation (to be used by screen capture)
def _kmp(needle, haystack, _dummy):
    # build table of shift amounts
    shifts = [1] * (len(needle) + 1)
    shift = 1
    for pos in range(len(needle)):
        while shift <= pos and needle[pos] != needle[pos-shift]:
            shift += shifts[pos-shift]
        shifts[pos+1] = shift

    # do the actual search
    startPos = 0
    matchLen = 0
    for c in haystack:
        while matchLen == len(needle) or \
                matchLen >= 0 and needle[matchLen] != c:
            startPos += shifts[matchLen]
            matchLen -= shifts[matchLen]
        matchLen += 1
        if matchLen == len(needle):
            yield startPos


def _steppingFind(needle, haystack, step):
    for startPos in range(0, len(haystack) - len(needle) + 1):
        foundMatch = True
        for pos in range(0, len(needle), step):
            if haystack[startPos + pos] != needle[pos]:
                foundMatch = False
                break
        if foundMatch:
            yield startPos


def center(coords):
    return (coords[0] + int(coords[2] / 2), coords[1] + int(coords[3] / 2))


def pixelMatchesColor(x, y, expectedRGBColor, tolerance=0):
    pix = pixel(x, y)
    if len(pix) == 3 or len(expectedRGBColor) == 3:  # RGB mode
        r, g, b = pix[:3]
        exR, exG, exB = expectedRGBColor[:3]
        return (abs(r - exR) <= tolerance) and (abs(g - exG) <= tolerance) and (abs(b - exB) <= tolerance)
    elif len(pix) == 4 and len(expectedRGBColor) == 4:  # RGBA mode
        r, g, b, a = pix
        exR, exG, exB, exA = expectedRGBColor
        return (abs(r - exR) <= tolerance) and (abs(g - exG) <= tolerance) and (abs(b - exB) <= tolerance) and (abs(a - exA) <= tolerance)
    else:
        assert False, 'Color mode was expected to be length 3 (RGB) or 4 (RGBA), but pixel is length %s and expectedRGBColor is length %s' % (
            len(pix), len(expectedRGBColor))


def pixel(x, y):
    if sys.platform == 'win32':
        # On Windows, calling GetDC() and GetPixel() is twice as fast as using our screenshot() function.
        hdc = windll.user32.GetDC(0)
        color = windll.gdi32.GetPixel(hdc, x, y)
        # color is in the format 0xbbggrr https://msdn.microsoft.com/en-us/library/windows/desktop/dd183449(v=vs.85).aspx
        r = color % 256
        g = (color // 256) % 256
        b = color // (256 ** 2)
        return (r, g, b)
    else:
        return screenshot().getpixel((x, y))


# set the screenshot() function based on the platform running this module
if sys.platform.startswith('java'):
    raise NotImplementedError('Jython is not yet supported by PyScreeze.')
elif sys.platform == 'darwin':
    screenshot = _screenshot_osx
elif sys.platform == 'win32':
    screenshot = _screenshot_win32
    try:
        from PIL import ImageGrab
    except ImportError:
        pass
else:
    screenshot = _screenshot_linux

grab = screenshot  # for compatibility with Pillow/PIL's ImageGrab module.

# set the locateAll function to use opencv if possible; python 3 needs opencv 3.0+
if useOpenCV:
    locateAll = _locateAll_opencv
    if not RUNNING_PYTHON_2 and cv2.__version__ < '3':
        locateAll = _locateAll_python
else:
    locateAll = _locateAll_python
