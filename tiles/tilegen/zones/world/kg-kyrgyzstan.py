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
    # Region: KG
    # Region Name: Kyrgyzstan

	render_tiles((72.2486,39.1919,72.2297,39.2453), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((72.2297,39.2453,72.3064,39.2572), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((72.3064,39.2572,72.2297,39.2453), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((71.7731,39.2781,71.8572,39.2867), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((71.8572,39.2867,72.1092,39.2881), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((72.1092,39.2881,71.8572,39.2867), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((72.3858,39.3358,72.3422,39.3364), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((72.3422,39.3364,72.3858,39.3358), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((71.7314,39.3375,72.3422,39.3364), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((72.1017,39.3414,71.7314,39.3375), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((73.0283,39.3517,71.9792,39.3519), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((72.4975,39.3517,71.9792,39.3519), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((71.9792,39.3519,73.0283,39.3517), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((73.1539,39.3533,71.9792,39.3519), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((72.4158,39.3586,72.8583,39.3625), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((72.8583,39.3625,72.5931,39.3639), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((72.5931,39.3639,72.8583,39.3625), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((72.9489,39.3664,72.5931,39.3639), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((72.0767,39.3747,72.5386,39.3819), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((72.5386,39.3819,73.0986,39.3825), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((73.0986,39.3825,72.5386,39.3819), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((70.8011,39.3889,71.7744,39.3911), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((71.7744,39.3911,70.8011,39.3889), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((73.3439,39.3947,71.7744,39.3911), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((70.7478,39.3986,70.9978,39.4011), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((70.9978,39.4011,73.3603,39.4014), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((73.3603,39.4014,70.9978,39.4011), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((70.8897,39.4019,73.3603,39.4014), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((72.6642,39.4019,73.3603,39.4014), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((70.9525,39.4103,70.8486,39.4111), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((70.8486,39.4111,70.9525,39.4103), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((71.0328,39.4119,70.8486,39.4111), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((70.7206,39.4192,71.0328,39.4119), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((70.9219,39.4353,73.3697,39.4419), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((73.3697,39.4419,70.9219,39.4353), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((71.605,39.4486,73.3697,39.4419), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((73.67244,39.45895,71.5425,39.4611), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((71.5425,39.4611,71.7567,39.4622), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((71.7567,39.4622,71.5425,39.4611), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((73.4914,39.47,73.84802,39.47498), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((73.84802,39.47498,70.7244,39.4767), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((70.7244,39.4767,73.84802,39.47498), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((71.515,39.4989,70.6739,39.5075), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((70.6739,39.5075,71.0972,39.5106), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((71.0972,39.5106,70.6739,39.5075), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((69.3406,39.5169,71.0972,39.5106), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((71.2753,39.5169,71.0972,39.5106), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((70.2347,39.5261,70.2692,39.5292), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((70.2692,39.5292,69.4458,39.5308), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((69.4458,39.5308,70.2692,39.5292), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((71.203,39.5336,70.0025,39.5339), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((70.0025,39.5339,71.203,39.5336), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((69.3625,39.5344,70.0025,39.5339), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((69.8428,39.5375,69.3061,39.5394), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((69.3061,39.5394,69.8428,39.5375), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((69.5436,39.5461,69.3061,39.5394), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((70.1631,39.5539,69.9431,39.5586), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((69.9431,39.5586,69.3844,39.5592), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((69.3844,39.5592,69.9431,39.5586), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((71.3161,39.5647,71.5531,39.5672), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((71.5531,39.5672,71.3161,39.5647), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((69.7728,39.5764,70.4072,39.5775), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((70.4072,39.5775,69.7728,39.5764), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((69.5897,39.5789,70.0525,39.58), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((70.0525,39.58,70.6339,39.5808), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((70.6339,39.5808,70.0525,39.58), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((70.5489,39.5822,70.6339,39.5808), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((70.3561,39.5822,70.6339,39.5808), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((69.7081,39.5878,70.4172,39.5919), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((70.4172,39.5919,69.7081,39.5878), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((73.95609,39.59776,71.4444,39.6025), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((71.4444,39.6025,71.4064,39.6064), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((71.4064,39.6064,70.4919,39.6083), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((70.4919,39.6083,71.4064,39.6064), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((71.4797,39.6203,70.2275,39.6247), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((70.2275,39.6247,71.4797,39.6203), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((69.3114,39.6817,70.2275,39.6247), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((69.2492,39.7544,73.84164,39.76249), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((73.84164,39.76249,69.2492,39.7544), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((73.85025,39.82582,69.265,39.8603), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((69.265,39.8603,73.85025,39.82582), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((69.425,39.9019,70.4981,39.9069), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((70.4981,39.9069,69.425,39.9019), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((69.5261,39.9319,70.4672,39.9364), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((70.4672,39.9364,69.5261,39.9319), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((70.5283,39.9503,69.3981,39.9519), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((69.3981,39.9519,70.5283,39.9503), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((70.6031,39.9583,69.3981,39.9519), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((69.5003,39.9686,70.4925,39.9736), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((70.4925,39.9736,69.5003,39.9686), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((70.6436,39.9894,69.3383,39.9964), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((69.3383,39.9964,70.6436,39.9894), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((70.5522,40.0094,69.3383,39.9964), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((70.5603,40.0264,69.4839,40.0361), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((69.4839,40.0361,70.6617,40.0369), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((70.6617,40.0369,69.4839,40.0361), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((73.99442,40.0461,70.6617,40.0369), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((70.5422,40.0461,70.6617,40.0369), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((70.3486,40.0831,74.3222,40.09276), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((74.3222,40.09276,70.3486,40.0831), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((70.6611,40.1036,69.5722,40.1072), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((69.5722,40.1072,70.6611,40.1036), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((69.6058,40.1119,74.19801,40.11388), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((74.19801,40.11388,69.6058,40.1119), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((69.5408,40.1314,70.2861,40.1328), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((70.2861,40.1328,69.5408,40.1314), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((70.7756,40.135,70.2861,40.1328), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((70.1728,40.1419,71.7106,40.1458), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((71.7106,40.1458,70.1728,40.1419), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((70.8336,40.1597,74.48303,40.16805), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((74.48303,40.16805,70.9181,40.1689), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((70.9181,40.1689,74.48303,40.16805), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((71.6875,40.1689,74.48303,40.16805), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((70.8197,40.1714,70.9181,40.1689), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((70.8614,40.1797,70.9744,40.1811), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((70.9744,40.1811,70.8614,40.1797), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((71.7972,40.1839,70.9744,40.1811), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((71.5628,40.2061,71.6217,40.2064), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((71.6217,40.2064,71.5628,40.2061), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((70.9964,40.2153,70.0242,40.2164), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((70.0242,40.2164,70.9964,40.2153), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((71.6881,40.2208,70.0242,40.2164), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((71.4903,40.2328,71.9572,40.2389), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((71.9572,40.2389,70.98216,40.24466), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((70.98216,40.24466,72.0419,40.2469), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((72.0419,40.2469,70.98216,40.24466), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((71.9831,40.2528,71.6347,40.2553), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((71.6347,40.2553,71.9831,40.2528), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((71.6656,40.2611,72.0494,40.2633), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((72.0494,40.2633,71.8633,40.2642), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((71.8633,40.2642,72.0494,40.2633), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((71.2172,40.2692,70.9992,40.2703), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((70.9992,40.2703,71.2172,40.2692), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((71.4211,40.2728,70.9992,40.2703), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((71.4644,40.2753,71.0642,40.2775), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((71.0642,40.2775,71.4644,40.2753), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((71.9803,40.2925,75.90385,40.30138), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((75.90385,40.30138,71.39,40.3019), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((71.39,40.3019,75.90385,40.30138), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((71.3089,40.3033,71.39,40.3019), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((75.68968,40.30915,71.3089,40.3033), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((71.9744,40.3183,74.87775,40.32471), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((74.87775,40.32471,71.9744,40.3183), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((71.2736,40.3319,74.72414,40.33665), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((74.72414,40.33665,71.2736,40.3319), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((76.32803,40.35416,74.87219,40.36832), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((74.87219,40.36832,72.0983,40.3725), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((72.0983,40.3725,76.18663,40.37554), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((76.18663,40.37554,72.0983,40.3725), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((76.04524,40.38888,72.4236,40.3889), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((72.4236,40.3889,76.04524,40.38888), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((75.66136,40.39832,76.44218,40.39915), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((76.44218,40.39915,75.66136,40.39832), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((74.81108,40.41749,72.2406,40.4264), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((72.2406,40.4264,72.1103,40.4308), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((72.1103,40.4308,72.2956,40.4311), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((72.2956,40.4311,72.1103,40.4308), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((72.2375,40.4397,75.69662,40.44498), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((75.69662,40.44498,72.2764,40.4458), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((72.2764,40.4458,75.69662,40.44498), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((75.05885,40.44776,72.2764,40.4458), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((76.28996,40.45138,76.2697,40.45221), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((76.2697,40.45221,76.28996,40.45138), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((72.1736,40.4603,72.2825,40.4625), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((72.2825,40.4625,72.453,40.4644), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((72.453,40.4644,72.2825,40.4625), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((75.27747,40.48248,72.453,40.4644), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((74.8447,40.5036,72.6486,40.5169), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((72.6486,40.5169,72.5972,40.5186), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((72.5972,40.5186,72.6486,40.5169), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((72.3811,40.5211,74.86913,40.52137), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((74.86913,40.52137,72.3811,40.5211), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((72.6725,40.5328,74.86913,40.52137), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((72.5225,40.5572,72.4736,40.5578), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((72.4736,40.5578,72.5225,40.5572), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((72.3958,40.56,72.4736,40.5578), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((72.7681,40.57,72.3958,40.56), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((72.69,40.5833,72.7681,40.57), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((72.3694,40.5986,76.63942,40.6086), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((76.63942,40.6086,72.3844,40.615), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((72.3844,40.615,76.63942,40.6086), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((75.59442,40.63998,75.56329,40.64388), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((75.56329,40.64388,75.59442,40.63998), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((72.8045,40.6747,72.9167,40.7), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((72.9167,40.7,72.8045,40.6747), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((76.64748,40.74026,73.0961,40.7714), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((73.0961,40.7714,76.64748,40.74026), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((73.1703,40.8172,72.8953,40.8228), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((72.8953,40.8228,73.1703,40.8172), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((73.1689,40.8322,72.8953,40.8228), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((73.0547,40.8428,73.1456,40.8486), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((73.1456,40.8486,73.0547,40.8428), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((76.79358,40.86249,72.8994,40.8678), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((72.8994,40.8678,72.7256,40.8692), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((72.7256,40.8692,72.8994,40.8678), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((73.0469,40.8731,72.8819,40.8767), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((72.8819,40.8767,73.0278,40.8789), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((73.0278,40.8789,72.8819,40.8767), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((72.6317,40.8853,73.0278,40.8789), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((76.78192,40.94082,72.5667,40.9647), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((72.5667,40.9647,72.5075,40.9756), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((72.5075,40.9756,77.50581,40.9861), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((77.50581,40.9861,72.5075,40.9756), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((72.1945,41.0043,76.86746,41.0111), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((76.86746,41.0111,72.5061,41.0153), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((72.5061,41.0153,76.86746,41.0111), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((72.3192,41.0322,72.405,41.0336), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((72.405,41.0336,72.3192,41.0322), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((77.02164,41.04999,72.2167,41.06), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((72.2167,41.06,77.02164,41.04999), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((72.3514,41.0828,78.16025,41.08554), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((78.16025,41.08554,72.3514,41.0828), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((71.1956,41.1167,71.4181,41.1186), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((71.4181,41.1186,71.2853,41.1192), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((71.2853,41.1192,71.4181,41.1186), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((71.3111,41.1225,71.2853,41.1192), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((71.2133,41.1369,71.44,41.1372), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((71.44,41.1372,71.2133,41.1369), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((72.0528,41.1589,71.1514,41.1642), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((71.1514,41.1642,71.1075,41.1644), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((71.1075,41.1644,71.1514,41.1642), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((71.35,41.1658,71.1075,41.1644), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((71.2714,41.1756,71.2025,41.1822), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((71.2025,41.1822,71.2714,41.1756), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((72.1836,41.1925,71.8933,41.1944), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((71.8933,41.1944,71.0547,41.1947), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((71.0547,41.1947,71.8933,41.1944), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((71.2433,41.1964,71.0547,41.1947), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((70.9331,41.1994,72.1219,41.2019), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((72.1219,41.2019,70.9331,41.1994), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((71.9994,41.2019,70.9331,41.1994), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((70.7847,41.2433,70.8472,41.2564), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((70.8472,41.2564,70.7847,41.2433), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((78.37358,41.27554,70.8472,41.2564), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((71.5503,41.3008,71.6036,41.3192), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((71.6036,41.3192,71.8872,41.3333), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((71.8872,41.3333,71.6036,41.3192), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((71.4381,41.3489,70.7928,41.3575), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((70.7928,41.3575,71.4381,41.3489), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((78.36552,41.36638,70.7928,41.3575), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((70.4742,41.4122,70.5403,41.4219), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((70.5403,41.4219,71.66,41.4289), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((71.66,41.4289,71.7483,41.4314), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((71.7483,41.4314,71.695,41.4319), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((71.695,41.4319,71.7483,41.4314), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((71.7253,41.4556,71.7639,41.4617), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((71.7639,41.4617,78.53108,41.46387), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((78.53108,41.46387,71.7639,41.4617), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((70.7119,41.4708,70.4217,41.4731), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((70.4217,41.4731,70.7119,41.4708), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((70.6694,41.4764,70.4217,41.4731), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((78.63997,41.48304,70.6694,41.4764), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((70.3767,41.4969,71.6206,41.5075), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((71.6206,41.5075,70.3767,41.4969), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((71.7164,41.5225,70.1917,41.525), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((70.1917,41.525,71.7164,41.5225), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((78.67081,41.53194,70.1917,41.525), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((71.6914,41.5564,70.1811,41.5775), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((71.6461,41.5564,70.1811,41.5775), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((70.1811,41.5775,71.6914,41.5564), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((70.47,41.7131,79.29608,41.78582), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((79.29608,41.78582,70.5261,41.7967), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((70.5261,41.7967,79.29608,41.78582), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((79.57053,41.84026,70.5261,41.7967), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((79.80136,41.90276,70.6853,41.905), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((70.6853,41.905,79.80136,41.90276), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((70.8442,41.9253,70.6853,41.905), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((79.85219,41.99999,70.8533,42.0164), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((70.8533,42.0164,80.2047,42.02915), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((80.2047,42.02915,79.97719,42.03416), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((79.97719,42.03416,80.2047,42.02915), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((70.8711,42.04,70.9869,42.0444), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((70.9869,42.0444,70.8711,42.04), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((80.27637,42.05971,70.9869,42.0444), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((71.1467,42.1319,71.2169,42.1394), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((71.2169,42.1394,71.1467,42.1319), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((71.2597,42.1703,80.28548,42.18236), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((80.28548,42.18236,71.2597,42.1703), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((71.2761,42.2042,80.1767,42.2197), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((80.1767,42.2197,71.2761,42.2042), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((70.9694,42.2528,70.9069,42.2669), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((70.9694,42.2528,70.9069,42.2669), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((70.9069,42.2669,70.9694,42.2528), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((71.0278,42.2964,71.0672,42.3028), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((71.0672,42.3028,80.1136,42.3036), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((80.1136,42.3036,71.0672,42.3028), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((70.8733,42.3131,80.1136,42.3036), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((80.0567,42.3369,70.8733,42.3131), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((70.9625,42.3883,73.5072,42.4047), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((73.5072,42.4047,73.5336,42.4189), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((73.5336,42.4189,70.955,42.4275), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((70.955,42.4275,73.3397,42.4328), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((73.3397,42.4328,79.9528,42.4342), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((79.9528,42.4342,73.4064,42.4344), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((73.4064,42.4344,79.9528,42.4342), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((79.8156,42.4461,79.5719,42.4531), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((79.5719,42.4531,79.8156,42.4461), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((71.0606,42.4608,79.5719,42.4531), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((79.4439,42.4722,79.7169,42.4742), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((79.7169,42.4742,79.4439,42.4722), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((71.0897,42.4808,70.9964,42.4867), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((70.9964,42.4867,71.0897,42.4808), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((73.3286,42.5125,73.2092,42.5214), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((73.2092,42.5214,73.3286,42.5125), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((73.4511,42.5333,71.0339,42.5347), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((71.0339,42.5347,73.4511,42.5333), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((72.9681,42.5389,71.0339,42.5347), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((72.9086,42.5483,72.9681,42.5389), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((73.1567,42.56,72.9086,42.5483), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((71.0311,42.5736,72.8328,42.5769), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((72.8328,42.5769,71.0311,42.5736), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((71.1672,42.6042,79.3567,42.6078), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((79.3567,42.6078,71.1672,42.6042), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((73.4325,42.6211,79.27,42.6292), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((79.27,42.6292,73.4325,42.6211), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((72.7919,42.6381,79.27,42.6292), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((72.7572,42.6561,72.7919,42.6381), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((79.2153,42.6792,71.1669,42.6869), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((71.1669,42.6869,72.5047,42.6878), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((72.5047,42.6878,71.1669,42.6869), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((72.5992,42.6922,72.5047,42.6878), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((71.2275,42.7067,73.4608,42.7106), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((73.4608,42.7106,71.2275,42.7067), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((79.1969,42.7267,73.4608,42.7106), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((71.3528,42.7436,72.1239,42.7572), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((72.1239,42.7572,71.2753,42.7592), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((71.2753,42.7592,79.0278,42.7597), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((79.0278,42.7597,71.2753,42.7592), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((71.5972,42.7636,71.5742,42.7653), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((71.5742,42.7653,71.5972,42.7636), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((72.2969,42.7736,78.9208,42.775), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((72.1717,42.7736,78.9208,42.775), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((78.9208,42.775,72.2969,42.7736), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((79.2097,42.7797,78.9739,42.7828), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((78.9739,42.7828,79.2097,42.7797), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((71.5028,42.7892,78.9739,42.7828), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((79.1947,42.7958,73.5258,42.8), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((73.5258,42.8,71.5303,42.8022), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((71.5303,42.8022,71.4247,42.8042), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((71.4247,42.8042,71.5303,42.8022), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((75.6761,42.8064,71.4247,42.8042), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((78.8017,42.8092,75.6761,42.8064), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((78.6892,42.8125,78.8017,42.8092), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((71.7256,42.8217,71.8089,42.8236), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((71.8089,42.8236,71.7256,42.8217), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((75.5686,42.8342,71.8697,42.8428), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((71.8697,42.8428,75.7472,42.8506), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((78.6539,42.8428,75.7472,42.8506), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((75.7472,42.8506,78.3369,42.8525), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((78.3369,42.8525,75.21,42.8533), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((75.21,42.8533,78.3369,42.8525), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((78.0939,42.8575,75.21,42.8533), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((77.9992,42.8672,77.8294,42.8708), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((77.8294,42.8708,77.9992,42.8672), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((78.2653,42.8756,77.8294,42.8708), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((78.5122,42.8853,78.4169,42.8856), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((78.4169,42.8856,78.5122,42.8853), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((77.5911,42.8875,78.4169,42.8856), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((76.4414,42.8919,77.5911,42.8875), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((73.5139,42.8964,77.3503,42.8967), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((77.3503,42.8967,73.5139,42.8964), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((76.6169,42.9003,77.812,42.9025), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((77.8975,42.9003,77.812,42.9025), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((77.812,42.9025,76.6169,42.9003), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((76.3431,42.9067,77.812,42.9025), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((77.7297,42.9147,77.66,42.9153), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((77.66,42.9153,77.7297,42.9147), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((76.4106,42.9161,76.7242,42.9167), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((76.7242,42.9167,77.2078,42.9172), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((77.2078,42.9172,76.7242,42.9167), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((76.6694,42.9203,77.5356,42.9214), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((77.5356,42.9214,76.6694,42.9203), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((76.5006,42.9233,76.0178,42.9236), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((76.0178,42.9236,76.5006,42.9233), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((76.3233,42.925,76.0178,42.9236), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((76.1872,42.9278,77.4597,42.9303), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((77.4597,42.9303,76.1872,42.9278), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((76.2403,42.9369,75.8025,42.9406), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((75.8025,42.9406,76.095,42.9414), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((76.095,42.9414,75.8025,42.9406), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((75.9108,42.9467,76.812,42.9469), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((76.812,42.9469,75.9108,42.9467), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((76.7744,42.9475,76.812,42.9469), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((73.5567,42.9569,77.1475,42.9656), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((77.1475,42.9656,77.0622,42.9706), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((77.0622,42.9706,77.1475,42.9656), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((76.8536,42.9819,74.8806,42.9828), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((74.8806,42.9828,76.8536,42.9819), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((74.7517,42.9931,76.9769,42.9964), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((76.9769,42.9964,74.7517,42.9931), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((73.5839,43.0386,74.6314,43.0661), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((74.6314,43.0661,73.5839,43.0386), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((73.9133,43.1228,73.8319,43.1292), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((73.8319,43.1292,74.5661,43.1325), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((74.5661,43.1325,73.8319,43.1292), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((74.4511,43.1522,74.5661,43.1325), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((74.0594,43.1881,74.3914,43.1953), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((74.3914,43.1953,74.0594,43.1881), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((74.235,43.2072,74.2933,43.2167), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((74.2933,43.2167,73.9731,43.2239), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((73.9731,43.2239,74.2933,43.2167), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((74.2358,43.2314,73.9731,43.2239), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")
	render_tiles((74.2011,43.2686,74.2358,43.2314), mapfile, tile_dir, 0, 11, "kg-kyrgyzstan")