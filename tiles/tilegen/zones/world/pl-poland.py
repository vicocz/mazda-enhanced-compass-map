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
    # Region: PL
    # Region Name: Poland

	render_tiles((22.88261,49.00635,22.82833,49.02582), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((22.82833,49.02582,22.67416,49.04415), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((22.67416,49.04415,22.82833,49.02582), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((22.558,49.07942,22.47499,49.09082), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((22.47499,49.09082,22.59805,49.09109), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((22.59805,49.09109,22.47499,49.09082), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((22.82166,49.1161,22.59805,49.09109), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((22.70027,49.16553,20.06888,49.17638), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((20.06888,49.17638,22.70027,49.16553), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((19.79444,49.19637,19.76611,49.21304), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((19.76611,49.21304,20.0026,49.21377), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((20.0026,49.21377,19.76611,49.21304), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((22.03027,49.21499,20.0026,49.21377), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((22.72555,49.21998,22.03027,49.21499), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((20.09944,49.22803,19.93638,49.23109), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((19.93638,49.23109,20.09944,49.22803), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((22.75999,49.28193,20.91083,49.2961), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((20.91083,49.2961,22.75999,49.28193), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((21.98027,49.31165,19.80889,49.31971), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((19.80889,49.31971,20.18166,49.32443), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((20.18166,49.32443,19.80889,49.31971), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((21.0975,49.36638,20.56722,49.37776), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((20.56722,49.37776,21.0975,49.36638), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((18.98055,49.3961,19.64111,49.40192), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((19.64111,49.40192,19.13889,49.40221), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((19.13889,49.40221,19.64111,49.40192), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((21.19749,49.40387,19.79166,49.40443), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((19.79166,49.40443,21.19749,49.40387), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((21.04944,49.40526,19.79166,49.40443), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((20.44083,49.40915,21.04944,49.40526), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((21.51305,49.41637,20.695,49.41749), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((20.695,49.41749,21.51305,49.41637), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((21.12583,49.43166,19.19694,49.43387), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((19.19694,49.43387,21.12583,49.43166), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((21.61277,49.43693,19.19694,49.43387), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((19.65194,49.45054,19.58527,49.4536), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((19.58527,49.4536,21.27888,49.45665), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((21.27888,49.45665,19.58527,49.4536), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((18.97944,49.49999,18.85416,49.51471), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((18.85416,49.51471,18.85333,49.51778), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((18.85333,49.51778,22.6561,49.51971), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((22.6561,49.51971,18.85333,49.51778), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((19.33861,49.52943,19.27639,49.53054), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((19.27639,49.53054,19.33861,49.52943), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((19.39027,49.56971,22.68083,49.57249), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((22.68083,49.57249,19.39027,49.56971), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((19.47555,49.60526,22.68083,49.57249), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((18.81166,49.67221,18.63277,49.72248), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((18.63277,49.72248,18.81166,49.67221), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((22.97471,49.83498,18.54667,49.91331), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((18.54667,49.91331,18.44722,49.91971), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((18.44722,49.91971,18.54667,49.91331), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((17.88778,49.97665,18.16027,49.99276), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((18.16027,49.99276,17.88778,49.97665), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((18.00722,50.01054,17.79889,50.0136), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((17.79889,50.0136,18.00722,50.01054), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((18.09111,50.02971,17.79889,50.0136), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((18.04722,50.05859,23.28333,50.08138), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((23.28333,50.08138,16.72527,50.09971), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((16.72527,50.09971,17.75,50.10221), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((17.75,50.10221,16.72527,50.09971), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((17.62555,50.13526,16.59055,50.13832), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((16.59055,50.13832,17.62555,50.13526), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((17.59777,50.15832,16.59055,50.13832), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((16.82138,50.18693,17.76249,50.20554), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((17.76249,50.20554,16.82138,50.18693), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((17.02805,50.23471,17.76249,50.20554), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((17.66555,50.2747,17.35278,50.27637), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((17.35278,50.27637,17.66555,50.2747), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((16.45861,50.3036,23.63083,50.30888), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((23.63083,50.30888,17.73333,50.31248), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((17.73333,50.31248,23.63083,50.30888), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((17.6961,50.32193,17.35389,50.32249), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((17.35389,50.32249,17.6961,50.32193), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((17.24694,50.33665,17.35389,50.32249), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((23.70777,50.38054,23.99166,50.4072), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((23.99166,50.4072,16.8675,50.41054), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((16.8675,50.41054,23.99166,50.4072), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((16.21055,50.41971,17.00417,50.42416), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((17.00417,50.42416,16.21055,50.41971), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((16.89027,50.43942,17.00417,50.42416), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((16.31083,50.50416,16.39666,50.51888), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((16.39666,50.51888,16.31083,50.50416), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((24.13277,50.54443,16.39666,50.51888), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((16.44916,50.57582,16.00972,50.60249), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((16.00972,50.60249,16.0625,50.61915), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((16.0625,50.61915,24.10833,50.62998), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((24.10833,50.62998,16.22138,50.63665), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((16.22138,50.63665,24.10833,50.62998), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((16.34777,50.65776,15.87055,50.66998), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((15.87055,50.66998,16.2375,50.67054), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((16.2375,50.67054,15.87055,50.66998), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((15.99722,50.67971,15.92083,50.68332), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((15.92083,50.68332,15.99722,50.67971), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((15.81833,50.74776,15.49305,50.78582), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((15.49305,50.78582,23.95472,50.78721), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((23.95472,50.78721,15.49305,50.78582), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((23.99582,50.8311,24.13055,50.83498), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((24.13055,50.83498,23.99582,50.8311), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((24.14471,50.85804,15.31056,50.85832), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((15.31056,50.85832,24.14471,50.85804), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((14.82885,50.86603,15.00528,50.8672), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((15.00528,50.8672,14.82885,50.86603), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((15.27083,50.92137,23.97305,50.94415), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((23.97305,50.94415,15.01917,50.9536), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((15.01917,50.9536,23.97305,50.94415), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((15.2775,50.96998,15.01917,50.9536), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((14.99083,51.00694,15.05111,51.00832), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((15.05111,51.00832,14.99083,51.00694), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((15.17278,51.01888,15.05111,51.00832), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((14.97528,51.10638,15.17278,51.01888), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((23.74944,51.20749,15.03805,51.26804), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((15.03805,51.26804,23.63222,51.30776), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((23.63222,51.30776,15.03805,51.26804), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((23.67138,51.43166,14.91083,51.48304), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((14.91083,51.48304,23.59208,51.52828), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((23.59208,51.52828,14.7175,51.55276), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((14.7175,51.55276,23.59208,51.52828), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((23.53917,51.59276,14.7175,51.55276), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((14.7575,51.65942,23.53917,51.59276), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((23.55389,51.74582,23.62638,51.79694), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((23.62638,51.79694,14.60194,51.8136), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((14.60194,51.8136,23.62638,51.79694), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((14.61611,51.85387,14.60194,51.8136), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((23.61166,51.91415,14.71639,51.94109), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((14.71639,51.94109,23.61166,51.91415), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((23.65638,52.04166,14.74722,52.05637), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((14.74722,52.05637,14.76353,52.07081), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((14.76353,52.07081,14.74722,52.05637), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((14.69305,52.10471,23.59833,52.10943), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((23.59833,52.10943,14.69305,52.10471), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((23.48583,52.14693,23.59833,52.10943), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((23.21138,52.22387,23.29388,52.22581), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((23.29388,52.22581,23.21138,52.22387), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((14.71333,52.23915,23.29388,52.22581), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((23.16888,52.2822,14.71333,52.23915), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((14.56694,52.32804,23.16888,52.2822), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((14.53444,52.39471,14.56694,52.32804), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((23.38416,52.50416,14.64111,52.56666), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((14.64111,52.56666,23.56361,52.58498), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((23.56361,52.58498,14.64111,52.56666), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((14.55111,52.62859,23.56361,52.58498), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((23.88388,52.67804,23.93388,52.7122), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((23.93388,52.7122,23.88388,52.67804), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((14.2575,52.79054,14.13333,52.83332), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((14.13333,52.83332,14.2575,52.79054), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((23.93499,52.89054,14.13333,52.83332), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((14.16472,52.96887,14.34222,53.04499), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((14.34222,53.04499,14.16472,52.96887), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((14.39083,53.14165,23.85416,53.21082), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((23.85416,53.21082,14.40861,53.21582), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((14.40861,53.21582,23.85416,53.21082), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((14.4453,53.27259,14.40861,53.21582), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((14.37555,53.42304,23.65805,53.52971), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((23.65805,53.52971,14.59555,53.59249), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((14.59555,53.59249,14.61167,53.65083), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((14.61167,53.65083,14.50083,53.66805), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((14.50083,53.66805,14.28639,53.66915), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((14.28639,53.66915,14.50083,53.66805), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((14.27782,53.69392,14.54444,53.71054), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((14.54444,53.71054,14.27782,53.69392), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((14.61944,53.76443,14.58778,53.80332), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((14.58778,53.80332,14.38889,53.83276), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((14.38889,53.83276,14.62917,53.84888), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((14.62917,53.84888,14.55833,53.85721), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((14.55833,53.85721,14.41639,53.85944), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((14.41639,53.85944,14.55833,53.85721), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((14.42472,53.86749,14.21742,53.86866), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((14.21742,53.86866,14.42472,53.86749), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((14.3625,53.8761,23.52111,53.87859), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((23.52111,53.87859,14.3625,53.8761), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((14.43111,53.89971,14.20333,53.90942), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((14.20333,53.90942,14.40861,53.91749), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((14.40861,53.91749,14.20333,53.90942), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((14.22598,53.92825,14.40861,53.91749), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((23.50375,53.94716,14.22598,53.92825), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((14.55944,53.97665,23.47499,53.99526), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((23.47499,53.99526,14.55944,53.97665), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((23.51778,54.03027,14.95389,54.06332), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((14.95389,54.06332,23.51778,54.03027), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((23.48444,54.13832,15.34111,54.15443), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((15.34111,54.15443,23.48444,54.13832), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((15.76417,54.21721,23.34194,54.24332), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((23.34194,54.24332,16.09222,54.25193), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((16.09222,54.25193,23.34194,54.24332), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((16.11305,54.26888,16.17333,54.27165), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((16.17333,54.27165,16.11305,54.26888), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((23.06611,54.30804,16.235,54.31805), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((16.235,54.31805,23.06611,54.30804), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((21.35333,54.32832,22.07472,54.33498), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((22.07472,54.33498,21.35333,54.32832), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((19.00402,54.34263,16.33278,54.34943), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((16.33278,54.34943,19.00402,54.34263), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((22.77,54.35999,20.64166,54.36665), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((20.64166,54.36665,22.7828,54.36666), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((22.7828,54.36666,20.64166,54.36665), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((18.72194,54.37638,23,54.38304), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((23,54.38304,18.72194,54.37638), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((19.43921,54.39581,16.32972,54.39832), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((16.32972,54.39832,19.43921,54.39581), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((22.86333,54.40859,16.32972,54.39832), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((19.99083,54.42054,22.86333,54.40859), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((18.58528,54.43332,19.81192,54.44605), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((19.81192,54.44605,18.58528,54.43332), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((19.62447,54.46149,19.66563,54.46691), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((19.66563,54.46691,19.63651,54.47107), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((19.66563,54.46691,19.63651,54.47107), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((19.63651,54.47107,19.66563,54.46691), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((16.50639,54.52915,19.63651,54.47107), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((16.92305,54.59999,18.48361,54.62888), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((18.48361,54.62888,18.81194,54.63999), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((18.81194,54.63999,18.52083,54.64193), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((18.52083,54.64193,18.81194,54.63999), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((17.07528,54.6761,18.70307,54.67729), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((18.70307,54.67729,17.07528,54.6761), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((18.40611,54.73444,17.43417,54.75277), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((17.43417,54.75277,18.40611,54.73444), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((18.43305,54.78638,18.45805,54.78805), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((18.45805,54.78805,18.43305,54.78638), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((17.85972,54.81638,18.335,54.83665), mapfile, tile_dir, 0, 11, "pl-poland")
	render_tiles((18.335,54.83665,17.85972,54.81638), mapfile, tile_dir, 0, 11, "pl-poland")