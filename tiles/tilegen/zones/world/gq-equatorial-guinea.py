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
    # Region: GQ
    # Region Name: Equatorial Guinea

	render_tiles((11.35389,1.00194,10.68444,1.0025), mapfile, tile_dir, 0, 11, "gq-equatorial-guinea")
	render_tiles((10.01472,1.00194,10.68444,1.0025), mapfile, tile_dir, 0, 11, "gq-equatorial-guinea")
	render_tiles((10.68444,1.0025,9.8045,1.00255), mapfile, tile_dir, 0, 11, "gq-equatorial-guinea")
	render_tiles((9.8045,1.00255,10.68444,1.0025), mapfile, tile_dir, 0, 11, "gq-equatorial-guinea")
	render_tiles((9.58055,1.04,9.8045,1.00255), mapfile, tile_dir, 0, 11, "gq-equatorial-guinea")
	render_tiles((9.84472,1.07917,9.66833,1.08222), mapfile, tile_dir, 0, 11, "gq-equatorial-guinea")
	render_tiles((9.66833,1.08222,9.84472,1.07917), mapfile, tile_dir, 0, 11, "gq-equatorial-guinea")
	render_tiles((9.72139,1.09667,9.66833,1.08222), mapfile, tile_dir, 0, 11, "gq-equatorial-guinea")
	render_tiles((9.39389,1.11167,9.55111,1.11861), mapfile, tile_dir, 0, 11, "gq-equatorial-guinea")
	render_tiles((9.55111,1.11861,9.39389,1.11167), mapfile, tile_dir, 0, 11, "gq-equatorial-guinea")
	render_tiles((9.5125,1.13389,9.55111,1.11861), mapfile, tile_dir, 0, 11, "gq-equatorial-guinea")
	render_tiles((9.3575,1.18167,9.5125,1.13389), mapfile, tile_dir, 0, 11, "gq-equatorial-guinea")
	render_tiles((11.34889,1.50305,9.67444,1.57083), mapfile, tile_dir, 0, 11, "gq-equatorial-guinea")
	render_tiles((9.67444,1.57083,9.61139,1.58667), mapfile, tile_dir, 0, 11, "gq-equatorial-guinea")
	render_tiles((9.61139,1.58667,9.63333,1.59167), mapfile, tile_dir, 0, 11, "gq-equatorial-guinea")
	render_tiles((9.63333,1.59167,9.61139,1.58667), mapfile, tile_dir, 0, 11, "gq-equatorial-guinea")
	render_tiles((9.61194,1.66028,9.63333,1.59167), mapfile, tile_dir, 0, 11, "gq-equatorial-guinea")
	render_tiles((9.81444,1.93139,10.02291,2.16737), mapfile, tile_dir, 0, 11, "gq-equatorial-guinea")
	render_tiles((10.02291,2.16737,10.67361,2.16778), mapfile, tile_dir, 0, 11, "gq-equatorial-guinea")
	render_tiles((10.02291,2.16737,10.67361,2.16778), mapfile, tile_dir, 0, 11, "gq-equatorial-guinea")
	render_tiles((10.67361,2.16778,10.02291,2.16737), mapfile, tile_dir, 0, 11, "gq-equatorial-guinea")
	render_tiles((11.34038,2.16861,10.67361,2.16778), mapfile, tile_dir, 0, 11, "gq-equatorial-guinea")
	render_tiles((9.85083,2.2425,11.34038,2.16861), mapfile, tile_dir, 0, 11, "gq-equatorial-guinea")
	render_tiles((9.7725,2.32472,9.80855,2.34607), mapfile, tile_dir, 0, 11, "gq-equatorial-guinea")
	render_tiles((9.80855,2.34607,9.7725,2.32472), mapfile, tile_dir, 0, 11, "gq-equatorial-guinea")