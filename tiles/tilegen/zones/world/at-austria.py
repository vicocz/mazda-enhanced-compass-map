#!/usr/bin/env python

# Tooling Template for Tile Generation
# DO NOT MODIFY 


from math import pi,cos,sin,log,exp,atan
from subprocess import call
import sys, os
from Queue import Queue
import threading
import mapnik

DEG_TO_RAD = pi/180
RAD_TO_DEG = 180/pi

# Default number of rendering threads to spawn, should be roughly equal to number of CPU cores available
NUM_THREADS = 6


def minmax (a,b,c):
    a = max(a,b)
    a = min(a,c)
    return a

class GoogleProjection:
    def __init__(self,levels=18):
        self.Bc = []
        self.Cc = []
        self.zc = []
        self.Ac = []
        c = 256
        for d in range(0,levels):
            e = c/2;
            self.Bc.append(c/360.0)
            self.Cc.append(c/(2 * pi))
            self.zc.append((e,e))
            self.Ac.append(c)
            c *= 2
                
    def fromLLtoPixel(self,ll,zoom):
         d = self.zc[zoom]
         e = round(d[0] + ll[0] * self.Bc[zoom])
         f = minmax(sin(DEG_TO_RAD * ll[1]),-0.9999,0.9999)
         g = round(d[1] + 0.5*log((1+f)/(1-f))*-self.Cc[zoom])
         return (e,g)
     
    def fromPixelToLL(self,px,zoom):
         e = self.zc[zoom]
         f = (px[0] - e[0])/self.Bc[zoom]
         g = (px[1] - e[1])/-self.Cc[zoom]
         h = RAD_TO_DEG * ( 2 * atan(exp(g)) - 0.5 * pi)
         return (f,h)



class RenderThread:
    def __init__(self, tile_dir, mapfile, q, printLock, maxZoom):
        self.tile_dir = tile_dir
        self.q = q
        self.m = mapnik.Map(256, 256)
        self.printLock = printLock
        # Load style XML
        mapnik.load_map(self.m, mapfile, True)
        # Obtain <Map> projection
        self.prj = mapnik.Projection(self.m.srs)
        # Projects between tile pixel co-ordinates and LatLong (EPSG:4326)
        self.tileproj = GoogleProjection(maxZoom+1)


    def render_tile(self, tile_uri, x, y, z):

        # Calculate pixel positions of bottom-left & top-right
        p0 = (x * 256, (y + 1) * 256)
        p1 = ((x + 1) * 256, y * 256)

        # Convert to LatLong (EPSG:4326)
        l0 = self.tileproj.fromPixelToLL(p0, z);
        l1 = self.tileproj.fromPixelToLL(p1, z);

        # Convert to map projection (e.g. mercator co-ords EPSG:900913)
        c0 = self.prj.forward(mapnik.Coord(l0[0],l0[1]))
        c1 = self.prj.forward(mapnik.Coord(l1[0],l1[1]))

        # Bounding box for the tile
        if hasattr(mapnik,'mapnik_version') and mapnik.mapnik_version() >= 800:
            bbox = mapnik.Box2d(c0.x,c0.y, c1.x,c1.y)
        else:
            bbox = mapnik.Envelope(c0.x,c0.y, c1.x,c1.y)
        render_size = 256
        self.m.resize(render_size, render_size)
        self.m.zoom_to_box(bbox)
        if(self.m.buffer_size < 128):
            self.m.buffer_size = 128

        # Render image with default Agg renderer
        im = mapnik.Image(render_size, render_size)
        mapnik.render(self.m, im)
        im.save(tile_uri, 'png256')


    def loop(self):
        while True:
            #Fetch a tile from the queue and render it
            r = self.q.get()
            if (r == None):
                self.q.task_done()
                break
            else:
                (name, tile_uri, x, y, z) = r

            exists= ""
            if os.path.isfile(tile_uri):
                exists= "exists"
            else:
                self.render_tile(tile_uri, x, y, z)
            bytes=os.stat(tile_uri)[6]
            empty= ''

            if bytes == 103:
                empty = " Empty Tile "
                os.remove(tile_uri)

            self.printLock.acquire()
            print name, ":", z, x, y, exists, empty
            self.printLock.release()
            self.q.task_done()



def render_tiles(bbox, mapfile, tile_dir, minZoom=1,maxZoom=18, name="unknown", num_threads=NUM_THREADS, tms_scheme=False):
    print "render_tiles(",bbox, mapfile, tile_dir, minZoom,maxZoom, name,")"

    tile_dir = tile_dir + name + "/";

    # Launch rendering threads
    queue = Queue(32)
    printLock = threading.Lock()
    renderers = {}
    for i in range(num_threads):
        renderer = RenderThread(tile_dir, mapfile, queue, printLock, maxZoom)
        render_thread = threading.Thread(target=renderer.loop)
        render_thread.start()
        #print "Started render thread %s" % render_thread.getName()
        renderers[i] = render_thread

    if not os.path.exists(tile_dir):
         os.makedirs(tile_dir)

    gprj = GoogleProjection(maxZoom+1) 

    ll0 = (bbox[0],bbox[3])
    ll1 = (bbox[2],bbox[1])

    for z in range(minZoom,maxZoom + 1):
        px0 = gprj.fromLLtoPixel(ll0,z)
        px1 = gprj.fromLLtoPixel(ll1,z)

        # check if we have directories in place
        zoom = "%s" % z
        if not os.path.isdir(tile_dir + zoom):
            os.mkdir(tile_dir + zoom)
        for x in range(int(px0[0]/256.0),int(px1[0]/256.0)+1):
            # Validate x co-ordinate
            if (x < 0) or (x >= 2**z):
                continue
            # check if we have directories in place
            str_x = "%s" % x
            if not os.path.isdir(tile_dir + zoom + '/' + str_x):
                os.mkdir(tile_dir + zoom + '/' + str_x)
            for y in range(int(px0[1]/256.0),int(px1[1]/256.0)+1):
                # Validate x co-ordinate
                if (y < 0) or (y >= 2**z):
                    continue
                # flip y to match OSGEO TMS spec
                if tms_scheme:
                    str_y = "%s" % ((2**z-1) - y)
                else:
                    str_y = "%s" % y
                tile_uri = tile_dir + zoom + '/' + str_x + '/' + str_y + '.png'
                # Submit tile to be rendered into the queue
                t = (name, tile_uri, x, y, z)
                try:
                    queue.put(t)
                except KeyboardInterrupt:
                    raise SystemExit("Ctrl-c detected, exiting...")

    # Signal render threads to exit by sending empty request to queue
    for i in range(num_threads):
        queue.put(None)
    # wait for pending rendering jobs to complete
    queue.join()
    for i in range(num_threads):
        renderers[i].join()




if __name__ == "__main__":
    home = os.environ['HOME']
    try:
        mapfile = "../tilestyles/mazda/mazda.xml"
    except KeyError:
        print("[MapFile] Not found")
        sys.exit(1)
    try:
        # ./tilegen/zones/[zone]/[region]
        tile_dir = "../../../output/"
    except KeyError:
        print("[OutputDir] No output directory found")
        sys.exit(1)

    if not tile_dir.endswith('/'):
        tile_dir = tile_dir + '/'


    # ------------------------------------------------------------------------
    # Tile Render Data
    # Zone: world
    # Region: AT
    # Region Name: Austria

	render_tiles((14.57444,46.38749,14.59416,46.43748), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((14.59416,46.43748,14.15944,46.44082), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((14.15944,46.44082,14.59416,46.43748), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((14.42833,46.44637,14.15944,46.44082), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((14.08472,46.48859,14.81472,46.51276), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((14.81472,46.51276,13.71896,46.52554), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((13.71896,46.52554,14.81472,46.51276), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((13.41222,46.57443,12.89583,46.61276), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((12.89583,46.61276,14.87055,46.61582), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((14.87055,46.61582,15.50083,46.61804), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((15.50083,46.61804,14.87055,46.61582), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((15.10527,46.6572,16.02694,46.66137), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((16.02694,46.66137,15.10527,46.6572), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((12.43361,46.69526,15.64944,46.70971), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((15.64944,46.70971,12.43361,46.69526), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((15.99333,46.73721,15.64944,46.70971), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((11.01472,46.77248,12.35583,46.77748), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((12.35583,46.77748,11.01472,46.77248), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((12.28361,46.79137,10.73555,46.7986), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((10.73555,46.7986,12.28361,46.79137), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((10.76444,46.83415,15.99361,46.83471), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((15.99361,46.83471,10.76444,46.83415), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((10.56083,46.84859,16.1067,46.85139), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((16.1067,46.85139,10.56083,46.84859), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((10.17528,46.8586,12.295,46.8636), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((12.295,46.8636,10.06333,46.86499), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((10.06333,46.86499,12.295,46.8636), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((10.46357,46.86935,10.06333,46.86499), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((10.67278,46.87498,10.46357,46.86935), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((10.46624,46.88542,10.67278,46.87498), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((12.14444,46.91582,10.48861,46.93498), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((10.48861,46.93498,10.31083,46.95054), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((10.31083,46.95054,9.87361,46.9586), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((9.87361,46.9586,11.16444,46.9622), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((11.16444,46.9622,9.87361,46.9586), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((11.41166,46.97248,11.75583,46.97748), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((11.75583,46.97748,11.41166,46.97248), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((11.33916,46.99554,10.40083,47.0011), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((10.40083,47.0011,11.33916,46.99554), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((16.34694,47.00999,11.61527,47.01305), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((11.61527,47.01305,16.34694,47.00999), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((12.13111,47.01638,11.61527,47.01305), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((9.87555,47.02248,12.13111,47.01638), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((16.45916,47.02943,9.87555,47.02248), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((12.20444,47.03915,16.45916,47.02943), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((9.60183,47.04964,9.60542,47.05777), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((9.60542,47.05777,16.51694,47.06081), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((16.51694,47.06081,9.60542,47.05777), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((9.61124,47.06469,16.51694,47.06081), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((9.61739,47.07101,9.61124,47.06469), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((9.6229,47.07832,9.62928,47.08315), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((9.62928,47.08315,9.6229,47.07832), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((9.63331,47.09028,12.21111,47.09054), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((12.21111,47.09054,9.63331,47.09028), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((16.46805,47.09526,9.64095,47.09717), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((9.64095,47.09717,16.46805,47.09526), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((9.63833,47.10596,9.63313,47.11342), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((9.63313,47.11342,9.63487,47.12076), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((9.63487,47.12076,9.63313,47.11342), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((9.63763,47.1286,16.52777,47.13443), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((16.52777,47.13443,9.6305,47.13708), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((9.6305,47.13708,16.52777,47.13443), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((9.62813,47.14306,16.4561,47.14693), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((16.4561,47.14693,9.62813,47.14306), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((9.62345,47.15203,9.6153,47.15239), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((9.6153,47.15239,9.62345,47.15203), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((16.52055,47.15526,9.60672,47.15532), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((9.60672,47.15532,16.52055,47.15526), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((9.59972,47.15933,9.60672,47.15532), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((9.59402,47.16677,9.57586,47.16728), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((9.57586,47.16728,9.59402,47.16677), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((9.58489,47.16857,9.57586,47.16728), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((9.57247,47.17712,9.57485,47.18555), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((9.57485,47.18555,9.57843,47.19202), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((9.57843,47.19202,9.57485,47.18555), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((9.58276,47.19901,9.57843,47.19202), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((9.58292,47.20771,9.57928,47.21499), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((9.57928,47.21499,9.5726,47.22186), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((9.5726,47.22186,9.56334,47.22241), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((9.56334,47.22241,9.5726,47.22186), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((9.55402,47.22701,9.56334,47.22241), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((9.56017,47.23309,9.56713,47.23723), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((9.56713,47.23723,9.56017,47.23309), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((9.57262,47.24559,9.57502,47.24954), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((9.57502,47.24954,9.56316,47.25039), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((9.56316,47.25039,9.57502,47.24954), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((16.43861,47.25277,9.56316,47.25039), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((9.55448,47.25557,9.54704,47.25691), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((9.54704,47.25691,9.55448,47.25557), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((9.54041,47.26698,9.54704,47.25691), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((16.49166,47.27998,10.16972,47.2811), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((10.16972,47.2811,16.49166,47.27998), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((10.27444,47.28888,10.16972,47.2811), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((10.21416,47.31526,10.27444,47.28888), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((9.60528,47.35999,10.15444,47.36915), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((10.15444,47.36915,9.60528,47.35999), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((9.665,47.38137,10.21139,47.38638), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((10.21139,47.38638,10.08722,47.38721), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((10.08722,47.38721,10.21139,47.38638), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((11.10694,47.39638,10.97361,47.40054), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((10.97361,47.40054,11.10694,47.39638), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((11.2275,47.40054,11.10694,47.39638), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((16.45055,47.4072,10.97361,47.40054), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((10.10444,47.42887,11.23666,47.43304), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((11.23666,47.43304,11.20305,47.43526), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((11.20305,47.43526,10.47333,47.43554), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((10.47333,47.43554,11.20305,47.43526), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((16.64555,47.45277,11.40555,47.45387), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((11.40555,47.45387,16.64555,47.45277), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((9.65361,47.45554,11.40555,47.45387), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((10.95028,47.46027,9.65361,47.45554), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((10.08444,47.46027,9.65361,47.45554), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((13.005,47.46943,10.95028,47.46027), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((10.00333,47.48387,10.86583,47.49304), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((10.86583,47.49304,13.05305,47.49638), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((13.05305,47.49638,10.86583,47.49304), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((9.55825,47.50407,11.42194,47.50888), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((11.42194,47.50888,9.55825,47.50407), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((11.57444,47.51998,10.90972,47.52193), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((10.90972,47.52193,11.57444,47.51998), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((9.60555,47.52915,9.72729,47.53626), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((9.72729,47.53626,10.84861,47.53638), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((10.84861,47.53638,9.72729,47.53626), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((10.55444,47.53693,10.84861,47.53638), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((9.85416,47.53888,16.71249,47.53999), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((16.71249,47.53999,9.85416,47.53888), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((9.56761,47.54392,9.96333,47.54777), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((9.96333,47.54777,9.56761,47.54392), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((12.80972,47.55221,9.96333,47.54777), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((10.68555,47.55859,12.80972,47.55221), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((10.46527,47.55859,12.80972,47.55221), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((10.42694,47.57693,9.76305,47.58471), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((9.76305,47.58471,12.78778,47.58942), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((12.78778,47.58942,10.48277,47.59054), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((10.48277,47.59054,12.78778,47.58942), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((9.81361,47.5936,11.63333,47.59526), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((11.63333,47.59526,9.81361,47.5936), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((11.87861,47.60665,12.19611,47.60943), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((12.19611,47.60943,11.87861,47.60665), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((13.07417,47.61693,12.83083,47.61887), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((12.83083,47.61887,13.07417,47.61693), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((16.64888,47.62971,12.505,47.63749), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((12.505,47.63749,13.10028,47.64082), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((13.10028,47.64082,12.20639,47.64137), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((12.20639,47.64137,13.10028,47.64082), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((16.43388,47.66443,12.77389,47.67416), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((12.77389,47.67416,16.43388,47.66443), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((16.76194,47.68526,16.7973,47.688), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((16.7973,47.688,16.76194,47.68526), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((12.24389,47.6947,16.45055,47.69804), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((16.45055,47.69804,12.44167,47.69859), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((12.44167,47.69859,16.45055,47.69804), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((12.17722,47.70165,12.44167,47.69859), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((13.05833,47.70609,17.08361,47.71027), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((17.08361,47.71027,13.05833,47.70609), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((16.53249,47.71471,12.9175,47.71554), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((12.9175,47.71554,16.53249,47.71471), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((16.69645,47.73624,12.25722,47.74304), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((12.25722,47.74304,16.68666,47.74387), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((16.68666,47.74387,12.25722,47.74304), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((16.55583,47.7561,16.68666,47.74387), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((12.93972,47.78471,16.55583,47.7561), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((17.0575,47.84443,13.00889,47.85416), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((13.00889,47.85416,17.0575,47.84443), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((17.01583,47.86804,13.00889,47.85416), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((17.09055,47.88776,17.01583,47.86804), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((17.1036,47.9772,17.1799,48.00182), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((17.1799,48.00182,17.1036,47.9772), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((17.08083,48.07999,12.75667,48.12054), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((12.75667,48.12054,17.0681,48.14415), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((17.0681,48.14415,12.75667,48.12054), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((16.97668,48.17418,17.0681,48.14415), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((12.92952,48.2093,16.97668,48.17418), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((16.94972,48.27804,12.92952,48.2093), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((13.36861,48.35193,16.84083,48.36859), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((16.84083,48.36859,13.36861,48.35193), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((16.85611,48.41915,13.43389,48.41998), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((13.43389,48.41998,16.85611,48.41915), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((16.89639,48.48721,13.72666,48.51776), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((13.72666,48.51776,16.89639,48.48721), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((13.44833,48.5686,14.38111,48.57555), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((14.38111,48.57555,14.70028,48.58138), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((14.70028,48.58138,13.50528,48.58305), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((13.50528,48.58305,14.70028,48.58138), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((14.04167,48.61582,16.94486,48.6165), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((16.94486,48.6165,14.04167,48.61582), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((14.45861,48.64832,14.04527,48.67693), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((14.04527,48.67693,13.83333,48.69887), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((13.83333,48.69887,14.04527,48.67693), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((16.77388,48.72387,13.79305,48.72609), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((13.79305,48.72609,16.77388,48.72387), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((16.8866,48.73032,16.37055,48.73387), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((16.8866,48.73032,16.37055,48.73387), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((16.37055,48.73387,16.8866,48.73032), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((16.06055,48.76027,14.96111,48.76665), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((14.96111,48.76665,16.06055,48.76027), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((14.8125,48.78137,13.81463,48.78714), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((13.81463,48.78714,16.65583,48.78777), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((16.65583,48.78777,13.81463,48.78714), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((16.5275,48.81081,15.95417,48.82832), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((15.95417,48.82832,16.5275,48.81081), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((15.78528,48.87748,15.95417,48.82832), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((15.15972,48.9447,15.34055,48.98582), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((15.34055,48.98582,15.15222,49.00138), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((15.15222,49.00138,14.99416,49.01582), mapfile, tile_dir, 0, 11, "at-austria")
	render_tiles((14.99416,49.01582,15.15222,49.00138), mapfile, tile_dir, 0, 11, "at-austria")