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
    # Region: RO
    # Region Name: Romania

	render_tiles((25.36305,43.6247,25.57293,43.64828), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((25.57293,43.64828,25.36305,43.6247), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((25.22471,43.68748,25.08055,43.69109), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((25.08055,43.69109,24.33722,43.69443), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((24.33722,43.69443,25.08055,43.69109), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((25.00138,43.72359,28.58384,43.74776), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((28.58384,43.74776,23.89055,43.75638), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((23.89055,43.75638,24.50166,43.76138), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((24.50166,43.76138,25.86277,43.76638), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((25.86277,43.76638,24.50166,43.76138), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((28.22499,43.77304,25.86277,43.76638), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((23.06361,43.80221,28.22499,43.77304), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((22.85749,43.85332,23.41305,43.85582), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((23.41305,43.85582,22.85749,43.85332), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((27.99721,43.85915,23.41305,43.85582), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((22.84333,43.90498,28.64305,43.93526), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((28.64305,43.93526,27.72166,43.96471), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((27.72166,43.96471,27.82027,43.96582), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((27.82027,43.96582,27.72166,43.96471), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((26.11166,43.96832,27.82027,43.96582), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((27.95166,43.97887,26.11166,43.96832), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((22.90694,43.99887,27.91888,44.00555), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((27.91888,44.00555,22.90694,43.99887), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((22.99582,44.01415,27.39999,44.02193), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((27.39999,44.02193,22.99582,44.01415), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((27.6561,44.04249,26.4786,44.04943), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((26.4786,44.04943,27.6561,44.04249), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((23.04277,44.05665,26.4786,44.04943), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((23.03722,44.08443,27.29055,44.08804), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((27.29055,44.08804,23.03722,44.08443), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((22.88277,44.12887,27.27555,44.13304), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((27.27555,44.13304,26.92332,44.13665), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((26.92332,44.13665,27.27555,44.13304), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((28.63749,44.16471,28.66888,44.1661), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((28.66888,44.1661,28.63749,44.16471), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((22.69193,44.24306,28.6311,44.25388), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((28.6311,44.25388,22.69193,44.24306), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((28.64527,44.33138,22.53694,44.33637), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((22.53694,44.33637,28.64527,44.33138), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((28.74972,44.46416,22.14638,44.47915), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((22.14638,44.47915,22.45999,44.4822), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((22.45999,44.4822,28.83416,44.48499), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((28.83416,44.48499,22.45999,44.4822), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((22.08444,44.50304,28.83416,44.48499), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((22.69944,44.52248,22.20666,44.52499), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((22.20666,44.52499,22.69944,44.52248), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((22.76361,44.54749,22.60944,44.55221), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((22.60944,44.55221,22.76361,44.54749), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((22.7536,44.56915,28.73778,44.57277), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((28.73778,44.57277,22.7536,44.56915), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((28.83404,44.62377,28.94694,44.62777), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((28.94694,44.62777,28.83404,44.62377), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((21.98888,44.63693,28.79277,44.63999), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((28.79277,44.63999,21.98888,44.63693), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((28.85166,44.6486,28.79277,44.63999), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((22.31361,44.66415,28.77972,44.66943), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((28.77972,44.66943,21.62277,44.67221), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((21.62277,44.67221,28.77972,44.66943), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((28.99389,44.67693,21.62277,44.67221), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((28.99638,44.68999,28.99389,44.67693), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((28.90416,44.70999,22.43638,44.71443), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((22.43638,44.71443,28.90416,44.70999), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((28.79833,44.71944,22.43638,44.71443), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((28.97749,44.74582,21.60027,44.7536), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((21.60027,44.7536,28.97749,44.74582), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((21.56555,44.77165,29.14194,44.77776), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((29.14194,44.77776,21.40027,44.78082), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((21.40027,44.78082,29.14194,44.77776), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((29.13361,44.7911,28.93972,44.79721), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((28.93972,44.79721,29.13361,44.7911), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((21.36098,44.82261,28.94971,44.82471), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((28.94971,44.82471,21.36098,44.82261), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((29.14194,44.82971,28.94971,44.82471), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((29.09972,44.83527,29.14194,44.82971), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((29.05,44.84554,29.61083,44.84832), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((29.61083,44.84832,29.05,44.84554), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((21.3661,44.86443,29.61083,44.84832), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((21.55277,44.89082,28.8625,44.91582), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((28.8625,44.91582,29.04083,44.92443), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((29.04083,44.92443,21.55139,44.92804), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((21.55139,44.92804,29.04083,44.92443), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((28.90222,44.96693,29.10972,44.97166), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((29.10972,44.97166,28.90222,44.96693), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((21.3774,44.99497,29.04166,45.0036), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((29.04166,45.0036,21.3774,44.99497), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((29.66027,45.11277,21.51277,45.12331), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((21.51277,45.12331,29.66027,45.11277), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((29.70111,45.15887,29.64999,45.16332), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((29.64999,45.16332,29.70111,45.15887), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((21.48527,45.18082,29.64999,45.16332), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((29.66177,45.21024,29.62389,45.21304), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((29.62389,45.21304,29.66177,45.21024), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((28.7486,45.22498,29.62389,45.21304), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((28.79972,45.23776,28.55861,45.24609), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((28.55861,45.24609,28.79972,45.23776), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((28.75694,45.26554,28.55861,45.24609), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((29.67083,45.28749,21.09499,45.30832), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((21.09499,45.30832,28.78444,45.32082), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((28.78444,45.32082,29.00444,45.3211), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((29.00444,45.3211,28.78444,45.32082), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((28.31666,45.33749,20.98666,45.34582), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((20.98666,45.34582,29.63694,45.35027), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((29.63694,45.35027,20.98666,45.34582), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((29.56194,45.39526,28.2761,45.43332), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((28.2761,45.43332,29.31416,45.43776), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((29.31416,45.43776,28.2761,45.43332), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((28.21202,45.4482,29.31416,45.43776), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((20.78305,45.48471,28.21202,45.4482), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((28.165,45.5336,20.82388,45.53721), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((20.82388,45.53721,28.165,45.5336), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((28.06194,45.58998,20.76722,45.60582), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((20.76722,45.60582,28.06194,45.58998), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((28.16138,45.63943,20.76722,45.60582), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((20.72166,45.74054,20.80472,45.74415), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((20.80472,45.74415,20.72166,45.74054), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((20.79583,45.76915,20.80472,45.74415), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((28.10749,45.83582,28.12972,45.86749), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((28.12972,45.86749,20.59166,45.89415), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((20.59166,45.89415,28.12972,45.86749), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((20.37805,45.97803,28.08444,46.01166), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((28.08444,46.01166,20.37805,45.97803), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((20.26114,46.11533,20.33555,46.15804), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((20.33555,46.15804,28.13555,46.16915), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((28.13555,46.16915,20.33555,46.15804), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((20.72166,46.18443,20.76305,46.19915), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((20.76305,46.19915,20.72166,46.18443), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((20.75333,46.23888,20.82972,46.27721), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((21.05361,46.23888,20.82972,46.27721), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((20.82972,46.27721,20.75333,46.23888), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((21.18722,46.32999,20.82972,46.27721), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((21.19721,46.39137,21.2875,46.41443), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((21.2875,46.41443,21.19721,46.39137), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((28.25194,46.43942,21.2961,46.44748), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((21.2961,46.44748,28.25194,46.43942), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((21.26166,46.48693,28.20943,46.50249), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((28.20943,46.50249,21.26166,46.48693), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((28.24721,46.60832,21.32666,46.61998), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((21.32666,46.61998,28.24721,46.60832), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((21.43832,46.6486,21.32666,46.61998), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((28.21388,46.68443,21.43832,46.6486), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((21.60916,46.89499,28.07111,46.9911), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((28.07111,46.9911,21.69582,47.00082), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((21.69582,47.00082,28.07111,46.9911), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((21.65166,47.02554,27.99249,47.02859), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((27.99249,47.02859,21.65166,47.02554), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((27.80694,47.1636,21.86888,47.26221), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((21.86888,47.26221,21.9225,47.35443), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((21.9225,47.35443,27.57222,47.37109), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((27.57222,47.37109,22.00471,47.37498), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((22.00471,47.37498,27.57222,47.37109), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((27.57944,47.4547,27.46971,47.48859), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((27.46971,47.48859,22.01028,47.5086), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((22.01028,47.5086,27.46638,47.52387), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((27.46638,47.52387,22.01028,47.5086), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((27.32194,47.64165,24.89749,47.71609), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((24.89749,47.71609,27.28944,47.72359), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((27.28944,47.72359,25.02972,47.72887), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((25.02972,47.72887,27.28944,47.72359), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((22.42138,47.74387,22.31888,47.74582), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((22.31888,47.74582,22.42138,47.74387), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((25.12388,47.76388,22.61221,47.76859), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((22.61221,47.76859,25.12388,47.76388), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((27.23833,47.78526,22.44166,47.7911), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((22.44166,47.7911,27.23833,47.78526), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((24.81639,47.81304,22.44166,47.7911), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((22.77444,47.83637,24.81639,47.81304), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((24.6761,47.86027,22.77083,47.87943), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((22.77083,47.87943,25.23027,47.88137), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((25.23027,47.88137,22.77083,47.87943), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((24.23805,47.90331,24.66027,47.90637), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((24.66027,47.90637,24.23805,47.90331), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((24.13111,47.91081,24.66027,47.90637), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((24.16859,47.92334,23.87416,47.9286), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((23.87416,47.9286,25.46833,47.92971), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((25.46833,47.92971,23.87416,47.9286), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((24.53111,47.95277,22.89486,47.9533), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((22.89486,47.9533,24.53111,47.95277), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((23.97555,47.96054,22.93722,47.96499), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((22.93722,47.96499,27.16444,47.96776), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((27.16444,47.96776,22.93722,47.96499), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((23.48055,47.97748,26.0111,47.97942), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((26.0111,47.97942,23.48055,47.97748), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((26.15916,47.98499,23.03416,47.98998), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((23.03416,47.98998,23.64138,47.99276), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((23.64138,47.99276,23.03416,47.98998), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((23.54499,48.00843,22.93416,48.00888), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((22.93416,48.00888,23.54499,48.00843), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((23.0911,48.01582,22.93416,48.00888), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((26.27222,48.0761,23.12388,48.08832), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((23.12388,48.08832,26.27222,48.0761), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((23.17416,48.1086,23.12388,48.08832), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((27.00055,48.15554,26.31638,48.18637), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((26.31638,48.18637,26.89444,48.2047), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((26.31638,48.18637,26.89444,48.2047), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((26.89444,48.2047,26.31638,48.18637), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((26.635,48.24087,26.70777,48.25332), mapfile, tile_dir, 0, 11, "ro-romania")
	render_tiles((26.70777,48.25332,26.635,48.24087), mapfile, tile_dir, 0, 11, "ro-romania")