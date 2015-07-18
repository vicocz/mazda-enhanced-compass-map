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
    # Region: HR
    # Region Name: Croatia

	render_tiles((14.66083,44.96555,14.80667,44.97305), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((14.66083,44.96555,14.80667,44.97305), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((14.80667,44.97305,14.66083,44.96555), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((14.61472,44.98388,14.80667,44.97305), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((14.78389,45.01249,14.49583,45.02999), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((14.49583,45.02999,14.62833,45.03499), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((14.62833,45.03499,14.49583,45.02999), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((14.42889,45.07832,14.62833,45.03499), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((14.545,45.20415,14.59444,45.21387), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((14.59444,45.21387,14.545,45.20415), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((14.54917,45.2461,14.59444,45.21387), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((14.50361,44.61665,14.44305,44.63832), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((14.50361,44.61665,14.44305,44.63832), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((14.44305,44.63832,14.50361,44.61665), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((14.4625,44.72804,14.44305,44.63832), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((14.39278,44.90665,14.29805,44.92194), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((14.29805,44.92194,14.39278,44.90665), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((14.47167,44.97777,14.37556,44.99249), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((14.37556,44.99249,14.47167,44.97777), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((14.37694,45.05249,14.37556,44.99249), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((14.27361,45.11499,14.35777,45.16527), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((14.35777,45.16527,14.31167,45.17277), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((14.31167,45.17277,14.35777,45.16527), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((18.5261,42.39832,18.51026,42.4494), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((18.51026,42.4494,18.4603,42.4869), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((18.4603,42.4869,18.51026,42.4494), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((18.45529,42.56452,18.21472,42.57943), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((18.21472,42.57943,18.45529,42.56452), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((18.4119,42.6064,18.22749,42.60777), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((18.22749,42.60777,18.4119,42.6064), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((18.2686,42.6183,18.3625,42.6267), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((18.3625,42.6267,18.2686,42.6183), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((17.90639,42.74749,18.1003,42.7508), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((18.1003,42.7508,17.90639,42.74749), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((17.9989,42.7614,18.1003,42.7508), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((17.73527,42.79499,17.81083,42.8086), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((17.81083,42.8086,17.9225,42.8111), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((17.9225,42.8111,17.81083,42.8086), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((17.8828,42.8192,17.72138,42.82388), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((17.72138,42.82388,17.8828,42.8192), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((17.71694,42.84776,17.8453,42.8597), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((17.8453,42.8597,17.71694,42.84776), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((17.65554,42.89129,17.8425,42.9036), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((17.65554,42.89129,17.8425,42.9036), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((17.8425,42.9036,17.7864,42.9039), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((17.7864,42.9039,17.8425,42.9036), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((17.8214,42.9203,17.6981,42.9272), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((17.6981,42.9272,17.33416,42.93054), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((17.33416,42.93054,17.6981,42.9272), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((17.42138,42.96138,17.33416,42.93054), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((17.04694,43.03471,17.42138,42.96138), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((17.57956,42.94401,17.6767,42.9633), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((17.6767,42.9633,17.6842,42.9822), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((17.6842,42.9822,17.47694,42.98527), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((17.47694,42.98527,17.6842,42.9822), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((17.42472,43.05971,17.6303,43.0769), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((17.6303,43.0769,17.35416,43.08777), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((17.35416,43.08777,17.6303,43.0769), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((17.4533,43.1611,17.3944,43.2303), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((17.3944,43.2303,17.2981,43.2808), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((17.2981,43.2808,17.01666,43.29137), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((17.01666,43.29137,17.2981,43.2808), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((16.88444,43.40305,17.2561,43.4144), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((17.2561,43.4144,16.88444,43.40305), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((17.2719,43.4444,16.62305,43.44721), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((16.62305,43.44721,17.2719,43.4444), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((17.2617,43.4597,16.62305,43.44721), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((16.03944,43.4811,17.2617,43.4597), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((16.52805,43.50804,16.39416,43.51027), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((16.39416,43.51027,16.52805,43.50804), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((17.0983,43.5136,16.39416,43.51027), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((16.47305,43.53194,17.0983,43.5136), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((16.35361,43.5511,16.47305,43.53194), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((16.9764,43.5861,15.92361,43.5886), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((15.92361,43.5886,16.9764,43.5861), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((15.91722,43.63055,15.95083,43.64721), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((15.95083,43.64721,15.91722,43.63055), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((15.90361,43.69554,16.8408,43.7192), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((16.8408,43.7192,15.90361,43.69554), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((16.7228,43.7861,15.65667,43.82471), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((15.65667,43.82471,16.7014,43.8506), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((16.7014,43.8506,15.65667,43.82471), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((15.375,43.99721,16.5372,44.0136), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((16.5372,44.0136,15.375,43.99721), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((16.4389,44.0319,16.5372,44.0136), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((16.3547,44.0817,16.4389,44.0319), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((16.3022,44.1572,16.2494,44.1967), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((16.2494,44.1967,16.1431,44.1994), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((16.1431,44.1994,16.2494,44.1967), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((16.1783,44.2147,16.1431,44.1994), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((15.14055,44.2386,15.17944,44.24554), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((15.17944,44.24554,15.28416,44.24666), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((15.28416,44.24666,15.17944,44.24554), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((15.20611,44.25804,15.46639,44.26027), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((15.46639,44.26027,15.20611,44.25804), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((15.11333,44.26027,15.20611,44.25804), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((15.52611,44.26943,15.46639,44.26027), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((15.13305,44.28277,15.29583,44.29499), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((15.29583,44.29499,15.19194,44.29999), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((15.19194,44.29999,15.29583,44.29499), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((16.1839,44.3058,15.19194,44.29999), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((15.27139,44.33082,16.225,44.3358), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((16.225,44.3358,15.27139,44.33082), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((15.27666,44.36443,16.225,44.3358), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((16.1592,44.3939,15.27666,44.36443), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((16.1214,44.5047,16.0425,44.5539), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((16.0425,44.5539,14.97583,44.5961), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((14.97583,44.5961,16.0425,44.5539), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((15.9569,44.7,15.8547,44.7144), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((15.8547,44.7144,15.9569,44.7), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((14.88611,44.77165,15.7675,44.7761), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((15.7675,44.7761,14.88611,44.77165), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((13.88,44.8111,15.7364,44.8169), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((15.7364,44.8169,13.88,44.8111), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((13.975,44.82526,15.7364,44.8169), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((15.7983,44.8553,19.0381,44.8606), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((19.0381,44.8606,18.8408,44.8631), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((18.8408,44.8631,19.0381,44.8606), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((13.83222,44.86916,18.8408,44.8631), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((14.89083,44.88194,13.83222,44.86916), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((19.0047,44.9003,19.0761,44.9094), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((19.0761,44.9094,18.7678,44.9158), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((18.7678,44.9158,19.0136,44.9167), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((19.0136,44.9167,18.7678,44.9158), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((15.7697,44.9192,19.0136,44.9167), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((14.0425,44.93193,19.0367,44.9325), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((19.0367,44.9325,14.0425,44.93193), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((18.7633,44.9447,14.07111,44.94471), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((14.07111,44.94471,18.7633,44.9447), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((18.8008,44.9494,19.1453,44.9511), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((19.1453,44.9511,18.8008,44.9494), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((14.92083,44.96277,19.1453,44.9511), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((19.1428,44.9822,19.1053,44.9839), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((19.1053,44.9839,19.1428,44.9822), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((14.17056,44.9886,19.1053,44.9839), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((15.7875,44.9953,18.7939,44.9969), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((18.7939,44.9969,15.7875,44.9953), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((18.7311,44.9994,16.2925,45.0006), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((16.2925,45.0006,18.7311,44.9994), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((16.3536,45.0058,16.2925,45.0006), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((18.7314,45.0219,14.05611,45.02554), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((14.05611,45.02554,18.7314,45.0219), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((16.2097,45.0344,19.1153,45.0361), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((19.1153,45.0361,16.2097,45.0344), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((18.5272,45.0472,17.8517,45.0492), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((17.8517,45.0492,18.5272,45.0472), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((14.14333,45.05582,18.6553,45.0578), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((18.6553,45.0578,14.14333,45.05582), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((18.6692,45.0617,18.6122,45.0625), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((18.6122,45.0625,18.6692,45.0617), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((18.4739,45.065,18.6122,45.0625), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((18.5747,45.0689,18.4739,45.065), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((15.7647,45.0736,18.5494,45.0761), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((18.5494,45.0761,18.6869,45.0772), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((18.6869,45.0772,18.5494,45.0761), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((17.9328,45.08,18.6869,45.0772), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((18.1194,45.0831,18.6097,45.0842), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((18.6097,45.0842,18.2053,45.0847), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((18.2053,45.0847,18.6097,45.0842), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((16.16,45.0856,18.2053,45.0847), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((18.66,45.0878,16.16,45.0856), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((16.4,45.0903,18.66,45.0878), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((18.6756,45.0942,18.5731,45.0944), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((18.5731,45.0944,18.6756,45.0942), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((18.6386,45.0947,16.1206,45.095), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((16.1206,45.095,18.6386,45.0947), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((18.535,45.0956,16.1206,45.095), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((19.1042,45.0967,18.535,45.0956), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((13.62833,45.09832,19.1042,45.0967), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((18.3231,45.1031,18.0694,45.1044), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((18.0694,45.1044,18.3231,45.1031), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((18.4297,45.1064,18.0694,45.1044), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((17.5961,45.1089,17.4833,45.1108), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((17.9339,45.1089,17.4833,45.1108), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((17.4833,45.1108,17.5281,45.1111), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((17.5558,45.1108,17.5281,45.1111), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((17.5281,45.1111,17.4833,45.1108), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((14.8425,45.11166,17.5281,45.1111), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((17.9639,45.1128,14.8425,45.11166), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((16.395,45.1183,15.7844,45.1203), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((15.7844,45.1203,16.395,45.1183), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((14.21667,45.12332,19.0817,45.1261), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((19.0817,45.1261,13.62333,45.12749), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((13.62333,45.12749,17.4508,45.1281), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((17.4508,45.1281,13.62333,45.12749), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((16.1119,45.1281,13.62333,45.12749), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((18.0322,45.1289,19.1381,45.1292), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((19.1381,45.1292,18.0322,45.1289), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((18.2164,45.1297,19.1381,45.1292), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((17.5497,45.1317,18.2164,45.1297), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((17.4944,45.1364,17.6703,45.1367), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((17.6703,45.1367,17.4944,45.1364), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((18.2517,45.1386,18.07,45.1392), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((18.07,45.1392,18.2517,45.1386), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((17.3722,45.1406,17.4228,45.1419), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((17.4228,45.1419,17.3722,45.1406), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((16.4594,45.1444,19.1606,45.1458), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((19.1606,45.1458,16.4594,45.1444), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((17.2403,45.1483,19.1606,45.1458), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((17.1769,45.1483,19.1606,45.1458), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((18.0017,45.1522,17.2403,45.1483), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((17.4494,45.1592,16.0519,45.1594), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((16.0519,45.1594,17.4494,45.1592), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((15.7811,45.1619,16.0519,45.1594), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((19.1808,45.1736,19.4111,45.175), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((19.4111,45.175,19.3286,45.1758), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((19.3286,45.1758,19.4111,45.175), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((19.2617,45.1803,19.4239,45.1844), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((19.4239,45.1844,16.4761,45.1856), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((16.4761,45.1856,19.4239,45.1844), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((17.2672,45.1869,16.8239,45.1872), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((16.8239,45.1872,17.2672,45.1869), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((17.0706,45.1881,16.8239,45.1872), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((19.3189,45.1997,19.2986,45.2036), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((19.2986,45.2036,19.3189,45.1997), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((19.2231,45.2086,15.8342,45.2119), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((15.8342,45.2119,19.1636,45.2122), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((19.1636,45.2122,15.8342,45.2119), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((16.0231,45.215,15.9517,45.2158), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((15.9517,45.2158,17.0083,45.2161), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((17.0083,45.2161,15.9517,45.2158), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((16.5258,45.2244,14.61167,45.22582), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((14.61167,45.22582,17.0356,45.2267), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((17.0356,45.2267,16.9903,45.2269), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((16.9903,45.2269,17.0356,45.2267), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((15.9367,45.2286,16.9903,45.2269), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((16.595,45.2306,15.9367,45.2286), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((16.9686,45.2336,16.9322,45.2344), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((16.9322,45.2344,16.9686,45.2336), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((19.4178,45.2356,16.9322,45.2344), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((17.0106,45.2392,13.59528,45.23943), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((13.59528,45.23943,17.0106,45.2392), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((14.25916,45.24249,13.59528,45.23943), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((19.2603,45.2472,16.9722,45.2494), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((16.9722,45.2494,19.2603,45.2472), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((16.9397,45.2656,19.195,45.2686), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((19.195,45.2686,16.9397,45.2656), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((16.9136,45.2739,19.195,45.2686), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((19.2539,45.2739,19.195,45.2686), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((19.1289,45.2906,13.57583,45.30027), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((13.57583,45.30027,19.1008,45.3081), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((19.1008,45.3081,14.48278,45.3111), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((14.48278,45.3111,19.1008,45.3081), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((19.0853,45.3478,19.0386,45.3486), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((19.0386,45.3486,19.0853,45.3478), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((14.32944,45.35443,19.0386,45.3486), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((18.9825,45.3758,18.9814,45.3964), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((18.9814,45.3964,19.0358,45.4103), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((19.0358,45.4103,18.9814,45.3964), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((15.1686,45.4256,15.2242,45.4311), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((15.2242,45.4311,15.1686,45.4256), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((15.1881,45.4394,13.6914,45.4444), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((13.6914,45.4444,15.1881,45.4394), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((18.9944,45.4517,13.9069,45.4533), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((13.9069,45.4533,18.9944,45.4517), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((15.3353,45.4564,13.9069,45.4533), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((13.9867,45.46,15.2722,45.4617), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((15.2722,45.4617,13.9867,45.46), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((13.6153,45.4644,14.8178,45.4658), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((14.8178,45.4658,13.6153,45.4644), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((14.1314,45.4744,14.9072,45.4764), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((14.9072,45.4764,13.8586,45.4781), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((13.8586,45.4781,14.9072,45.4764), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((13.9972,45.48,13.8586,45.4781), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((15.3233,45.4822,14.3206,45.4842), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((14.3206,45.4842,14.3928,45.4861), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((14.3928,45.4861,19.0831,45.4878), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((15.0847,45.4861,19.0831,45.4878), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((19.0831,45.4878,15.0211,45.4894), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((15.0211,45.4894,18.9997,45.4908), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((18.9997,45.4908,13.49639,45.49082), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((13.49639,45.49082,18.9997,45.4908), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((14.7972,45.5014,14.2383,45.5056), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((14.2383,45.5056,13.56967,45.50707), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((13.56967,45.50707,13.9783,45.5078), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((13.9783,45.5078,13.56967,45.50707), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((15.3361,45.5103,19.1006,45.5122), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((19.1006,45.5122,15.3361,45.5103), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((13.9894,45.5222,14.9292,45.5244), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((14.9292,45.5244,13.9894,45.5222), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((14.4858,45.5297,14.7031,45.5328), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((14.7031,45.5328,14.4858,45.5297), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((14.6869,45.5367,18.9483,45.5378), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((18.9483,45.5378,14.6869,45.5367), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((15.3039,45.5378,14.6869,45.5367), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((19.0344,45.5422,18.9483,45.5378), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((19.0244,45.5608,18.9019,45.5703), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((18.9019,45.5703,14.6853,45.5742), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((14.6853,45.5742,18.9019,45.5703), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((14.5097,45.5981,15.2831,45.6081), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((15.2831,45.6081,18.9081,45.6167), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((18.9081,45.6167,14.6136,45.62), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((14.6136,45.62,18.9081,45.6167), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((14.5544,45.6311,14.6136,45.62), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((15.3919,45.6467,15.3481,45.6492), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((15.3481,45.6492,15.3919,45.6467), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((14.565,45.665,18.9689,45.6672), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((18.9689,45.6672,14.565,45.665), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((15.3472,45.675,14.6014,45.6753), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((14.6014,45.6753,15.3472,45.675), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((15.3028,45.6908,15.2833,45.6947), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((15.2833,45.6947,15.3358,45.6975), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((15.3358,45.6975,15.2833,45.6947), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((15.3681,45.7028,15.3358,45.6975), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((18.9092,45.7133,15.3586,45.7144), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((15.3586,45.7144,18.9092,45.7133), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((15.3086,45.7194,15.3586,45.7144), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((15.2919,45.7311,18.9561,45.7361), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((18.9561,45.7361,15.2919,45.7311), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((18.27897,45.76035,15.3225,45.7614), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((15.3225,45.7614,18.27897,45.76035), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((18.08249,45.76665,15.3225,45.7614), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((18.9586,45.7781,18.9333,45.7825), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((18.9333,45.7825,18.18916,45.78443), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((18.18916,45.78443,18.9333,45.7825), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((18.55944,45.80165,15.4822,45.8022), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((15.4822,45.8022,18.55944,45.80165), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((17.79944,45.80888,18.9244,45.8119), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((18.9244,45.8119,17.79944,45.80888), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((15.4447,45.8158,18.9244,45.8119), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((15.6567,45.8233,15.5383,45.8264), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((15.5383,45.8264,15.6567,45.8233), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((15.4994,45.8358,15.6978,45.8442), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((15.6978,45.8442,18.8592,45.8472), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((18.8592,45.8472,15.6094,45.8486), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((15.6094,45.8486,18.8592,45.8472), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((15.6794,45.8619,15.6094,45.8486), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((18.62916,45.87609,18.80305,45.88665), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((18.80305,45.88665,18.8281,45.89668), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((18.8281,45.89668,15.6906,45.9028), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((15.6906,45.9028,18.8281,45.89668), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((18.69916,45.9211,15.7236,45.9347), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((15.7236,45.9347,17.57666,45.94054), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((17.57666,45.94054,15.7236,45.9347), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((17.35861,45.94999,17.4261,45.9547), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((17.4261,45.9547,17.35861,45.94999), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((17.32055,45.97443,17.4261,45.9547), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((15.7,46.02,15.7183,46.0472), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((15.7183,46.0472,15.7,46.02), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((15.6294,46.0869,17.20972,46.11832), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((17.20972,46.11832,15.5997,46.1425), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((15.5997,46.1425,17.20972,46.11832), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((17.06416,46.20665,15.7811,46.2125), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((15.7811,46.2125,15.6519,46.2167), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((15.6519,46.2167,15.7811,46.2125), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((15.6767,46.2267,15.6519,46.2167), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((16.93916,46.24609,15.8217,46.2583), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((15.8217,46.2583,16.93916,46.24609), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((16.0172,46.2981,16.87638,46.3186), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((16.87638,46.3186,16.0811,46.3311), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((16.0811,46.3311,16.87638,46.3186), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((16.2939,46.3744,16.0783,46.3797), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((16.0783,46.3797,16.1925,46.3847), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((16.1925,46.3847,16.3039,46.3858), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((16.3039,46.3858,16.1925,46.3847), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((16.2631,46.3889,16.3039,46.3858), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((16.1447,46.4061,16.2689,46.4119), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((16.2689,46.4119,16.1447,46.4061), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((16.5772,46.4694,16.60924,46.47517), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((16.60924,46.47517,16.5772,46.4694), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((16.60924,46.47517,16.5772,46.4694), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((16.2514,46.4983,16.60924,46.47517), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((16.3007,46.53174,16.3978,46.5408), mapfile, tile_dir, 0, 11, "hr-croatia")
	render_tiles((16.3978,46.5408,16.3007,46.53174), mapfile, tile_dir, 0, 11, "hr-croatia")