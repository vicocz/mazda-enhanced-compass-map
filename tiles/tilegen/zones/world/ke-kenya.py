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
    # Region: KE
    # Region Name: Kenya

	render_tiles((39.20562,-4.67312,39.32582,-4.64), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((39.32582,-4.64,39.39832,-4.63722), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((39.39832,-4.63722,39.32582,-4.64), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((39.11998,-4.61,39.30082,-4.59722), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((39.30082,-4.59722,39.11998,-4.61), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((39.4511,-4.58194,39.30082,-4.59722), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((39.4336,-4.54695,39.4511,-4.58194), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((39.67165,-4.09222,39.56638,-4.08083), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((39.56638,-4.08083,39.67165,-4.09222), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((39.61137,-4.06083,39.68277,-4.05389), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((39.68277,-4.05389,39.61137,-4.06083), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((39.62249,-4.0375,39.55777,-4.03556), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((39.55777,-4.03556,39.62249,-4.0375), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((39.63915,-4.00195,39.74194,-3.98278), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((39.74194,-3.98278,39.65388,-3.9725), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((39.65388,-3.9725,39.74194,-3.98278), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((39.75888,-3.95056,39.65388,-3.9725), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((39.68332,-3.92472,39.75888,-3.95056), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((39.84888,-3.75639,37.78336,-3.65143), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((37.78336,-3.65143,39.87054,-3.64194), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((39.87054,-3.64194,37.78336,-3.65143), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((39.8611,-3.62333,39.78138,-3.60917), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((39.78138,-3.60917,39.8611,-3.62333), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((39.81026,-3.59417,39.78138,-3.60917), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((37.7336,-3.52611,37.6172,-3.5075), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((37.6172,-3.5075,37.7336,-3.52611), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((37.59999,-3.45028,39.96499,-3.4025), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((39.96499,-3.4025,37.61304,-3.3975), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((37.61304,-3.3975,39.96499,-3.4025), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((39.97415,-3.37583,37.61304,-3.3975), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((39.98777,-3.31972,37.71998,-3.31194), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((37.71998,-3.31194,39.98777,-3.31972), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((40.10805,-3.2925,37.71998,-3.31194), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((37.67526,-3.05139,37.63026,-3.01694), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((37.63026,-3.01694,37.67526,-3.05139), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((40.18526,-2.96306,37.63026,-3.01694), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((40.16444,-2.89361,40.18526,-2.96306), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((40.18832,-2.73333,40.25888,-2.645), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((40.25888,-2.645,40.18832,-2.73333), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((40.61665,-2.55667,40.52776,-2.52528), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((40.52776,-2.52528,40.61665,-2.55667), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((40.81026,-2.40417,40.82221,-2.36611), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((40.82221,-2.36611,40.81026,-2.40417), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((40.95749,-2.30639,40.77055,-2.29306), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((40.77055,-2.29306,40.9486,-2.28722), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((40.9486,-2.28722,40.77055,-2.29306), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((36.29527,-2.27929,40.9486,-2.28722), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((40.98305,-2.2525,40.88527,-2.22583), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((40.88527,-2.22583,40.92304,-2.22278), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((40.92304,-2.22278,40.88527,-2.22583), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((36.04519,-2.13995,36.01339,-2.12223), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((36.01339,-2.12223,36.04519,-2.13995), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((40.9311,-2.07278,40.97443,-2.05861), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((40.97443,-2.05861,40.9311,-2.07278), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((40.99915,-2.04028,40.97443,-2.05861), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((41.06999,-2.01472,40.97749,-1.99972), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((40.97749,-1.99972,40.90415,-1.99472), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((40.90415,-1.99472,41.18166,-1.99444), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((41.18166,-1.99444,40.90415,-1.99472), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((41.14193,-1.9875,41.18166,-1.99444), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((40.85082,-1.97861,41.28027,-1.97028), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((41.28027,-1.97028,40.85082,-1.97861), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((40.96888,-1.93806,35.67137,-1.93167), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((35.67137,-1.93167,40.96888,-1.93806), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((41.2161,-1.925,35.67137,-1.93167), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((41.00888,-1.90194,41.2161,-1.925), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((41.43416,-1.82806,41.00888,-1.90194), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((41.55772,-1.67436,41.55526,-1.59222), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((41.55526,-1.59222,34.98776,-1.55056), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((34.98776,-1.55056,41.55526,-1.59222), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((34.30526,-1.16806,34.06935,-1.05581), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((34.06935,-1.05581,34.02971,-1.03694), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((34.06935,-1.05581,34.02971,-1.03694), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((34.02971,-1.03694,34.06935,-1.05581), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((33.92033,-1.00149,34.02054,-1.00139), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((34.02054,-1.00139,33.92033,-1.00149), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((41.02971,-0.90639,34.02054,-1.00139), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((33.91859,-0.45278,33.97609,-0.13417), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((33.97609,-0.13417,33.9072,0.10306), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((40.98859,0,33.9072,0.10306), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((33.9072,0.10306,33.99947,0.23042), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((33.99947,0.23042,34.00423,0.23699), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((34.00423,0.23699,33.99947,0.23042), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((34.10777,0.35694,34.00423,0.23699), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((34.15998,0.60306,34.26082,0.64111), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((34.26082,0.64111,34.15998,0.60306), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((34.2911,0.68639,34.26082,0.64111), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((34.41081,0.82194,34.2911,0.68639), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((34.57748,1.0925,34.52744,1.11342), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((34.52744,1.11342,34.57748,1.0925), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((34.60582,1.15889,34.52744,1.11342), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((34.81971,1.23139,34.82971,1.28889), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((34.82971,1.28889,34.81971,1.23139), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((34.79221,1.39361,34.82971,1.28889), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((34.99999,1.67194,34.99943,1.87667), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((34.99943,1.87667,35.02609,1.91972), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((35.02609,1.91972,34.99943,1.87667), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((34.97915,1.99472,35.02609,1.91972), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((34.99499,2.09111,34.97915,1.99472), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((34.9447,2.21305,34.99499,2.09111), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((34.8822,2.41305,34.94054,2.45056), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((34.94054,2.45056,34.8822,2.41305), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((34.93581,2.50694,34.94054,2.45056), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((34.83915,2.60389,34.93581,2.50694), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((40.98631,2.83259,34.74971,2.85583), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((34.74971,2.85583,34.6622,2.86111), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((34.6622,2.86111,34.74971,2.85583), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((34.59082,2.93944,34.6622,2.86111), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((34.55915,3.11111,41.33693,3.1675), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((41.33693,3.1675,34.45415,3.18194), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((34.45415,3.18194,41.33693,3.1675), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((34.40498,3.40667,39.50499,3.41806), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((39.56026,3.40667,39.50499,3.41806), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((39.50499,3.41806,34.40498,3.40667), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((39.49804,3.45528,39.19693,3.47861), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((39.19693,3.47861,39.49804,3.45528), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((38.9136,3.51389,34.45554,3.52417), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((34.45554,3.52417,39.05554,3.52722), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((39.05554,3.52722,34.45554,3.52417), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((38.44804,3.59944,38.12109,3.61167), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((38.12109,3.61167,38.44804,3.59944), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((38.52887,3.65389,34.46332,3.67139), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((34.46332,3.67139,39.78276,3.67833), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((39.78276,3.67833,34.46332,3.67139), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((34.29943,3.70667,37.99804,3.72861), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((37.99804,3.72861,34.35499,3.73861), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((34.35499,3.73861,37.99804,3.72861), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((34.17609,3.77555,34.2636,3.78639), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((34.2636,3.78639,34.17609,3.77555), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((34.16331,3.82722,34.21054,3.84055), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((34.21054,3.84055,34.16331,3.82722), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((39.86665,3.86944,34.09943,3.88), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((34.09943,3.88,34.21415,3.8875), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((34.21415,3.8875,34.09943,3.88), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((41.31915,3.94444,41.83693,3.94778), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((41.83693,3.94778,41.31915,3.94444), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((34.12971,3.95444,41.83693,3.94778), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((41.12915,3.96278,34.12971,3.95444), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((41.77137,3.98611,41.91364,3.99046), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((41.91364,3.99046,41.77137,3.98611), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((41.91364,3.99866,41.91364,3.99046), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((40.3886,4.09889,34.0547,4.18555), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((34.0547,4.18555,33.9976,4.22176), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((33.9976,4.22176,34.0547,4.18555), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((40.78343,4.28762,33.9976,4.22176), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((36.97331,4.39667,36.04582,4.44666), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((36.04582,4.44666,36.97331,4.39667), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((36.19724,4.44666,36.97331,4.39667), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((36.64748,4.44666,36.97331,4.39667), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((35.95126,4.52098,36.04582,4.44666), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((34.37659,4.59915,34.38749,4.61), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((34.38749,4.61,35.05193,4.61361), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((35.05193,4.61361,35.50907,4.61666), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((35.50907,4.61666,35.61025,4.61734), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((35.61025,4.61734,35.69901,4.61794), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((35.69901,4.61794,35.71665,4.61805), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((35.71665,4.61805,35.69901,4.61794), mapfile, tile_dir, 0, 11, "ke-kenya")
	render_tiles((35.94032,4.62208,35.71665,4.61805), mapfile, tile_dir, 0, 11, "ke-kenya")