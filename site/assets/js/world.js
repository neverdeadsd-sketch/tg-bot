/* World geography for the globe.
 *
 * Coastlines as coarse lon/lat rings. The globe renders a dot matrix, so a dot
 * is either land or ocean — outlines only need to survive a ~1.5 degree grid,
 * which is roughly the fidelity you get from a printed atlas held at arm's
 * length. Every ring is closed implicitly; the first point is not repeated.
 */
(function (root) {
  'use strict';

  var LAND = {
    africa: [
      [-17,15],[-16,22],[-13,28],[-9,30],[-6,36],[3,37],[11,34],[20,31],[25,32],
      [32,31],[34,28],[37,22],[39,15],[43,12],[51,12],[48,5],[44,2],[41,-2],
      [40,-10],[40,-16],[35,-24],[32,-29],[27,-34],[18,-34],[12,-18],[11,-8],
      [9,0],[8,4],[3,6],[-4,5],[-9,5],[-13,9]
    ],
    eurasia: [
      [-10,36],[-9,43],[-4,48],[2,51],[5,53],[8,55],[5,58],[5,62],[12,68],
      [20,70],[30,70],[40,68],[60,70],[75,73],[90,75],[105,77],[113,74],
      [130,72],[145,70],[160,69],[170,66],[179,65],[170,60],[163,58],[156,51],
      [140,54],[135,45],[127,40],[122,38],[121,31],[110,21],[105,10],[100,6],
      [98,14],[92,21],[88,21],[80,10],[72,20],[68,24],[57,25],[50,29],[48,30],
      [50,25],[56,25],[58,20],[52,15],[45,13],[43,17],[39,21],[35,28],[34,31],
      [36,36],[28,41],[24,40],[20,39],[18,43],[13,45],[4,43],[0,39],[-6,36],
      [-9,37]
    ],
    northAmerica: [
      [-168,66],[-165,60],[-155,58],[-145,60],[-135,58],[-125,49],[-124,42],
      [-122,37],[-118,34],[-117,32],[-112,26],[-106,22],[-98,16],[-94,15],
      [-88,15],[-87,13],[-83,9],[-79,9],[-83,10],[-87,16],[-88,18],[-90,21],
      [-97,21],[-94,29],[-89,29],[-82,25],[-80,32],[-76,37],[-70,42],[-66,45],
      [-56,47],[-64,60],[-78,62],[-95,68],[-115,69],[-130,70],[-141,70],
      [-158,71]
    ],
    greenland: [
      [-45,60],[-50,65],[-55,70],[-60,76],[-45,83],[-30,83],[-20,76],[-22,70],
      [-38,65]
    ],
    southAmerica: [
      [-81,0],[-79,-8],[-71,-18],[-70,-25],[-73,-40],[-75,-52],[-68,-55],
      [-65,-45],[-62,-39],[-57,-35],[-53,-33],[-48,-25],[-40,-20],[-39,-13],
      [-35,-8],[-44,-2],[-50,0],[-52,5],[-60,8],[-72,11],[-77,8],[-79,2]
    ],
    australia: [
      [114,-22],[114,-33],[120,-34],[129,-32],[135,-35],[140,-38],[148,-38],
      [152,-32],[153,-26],[146,-19],[142,-11],[136,-12],[130,-12],[125,-14],
      [121,-19]
    ],
    italy:     [[12,44],[15,42],[18,40],[16,38],[13,41],[10,43]],
    sicily:    [[12,38],[15,38],[15,37],[12,37]],
    britain:   [[-5,50],[-6,55],[-3,58],[-2,56],[0,53],[1,51]],
    ireland:   [[-10,51],[-10,55],[-6,55],[-6,52]],
    iceland:   [[-24,65],[-14,66],[-14,64],[-22,63]],
    japan:     [[130,31],[131,34],[136,36],[141,41],[145,44],[141,45],[140,38],[136,34],[133,33]],
    sumatra:   [[95,5],[105,-6],[106,-7],[100,0]],
    java:      [[105,-6],[114,-8],[112,-8],[106,-7]],
    borneo:    [[109,2],[117,4],[119,-3],[110,-4]],
    sulawesi:  [[120,1],[125,1],[123,-5],[119,-4]],
    newGuinea: [[131,-1],[141,-3],[150,-10],[143,-9],[134,-8]],
    newZealand:[[173,-35],[178,-38],[174,-41],[170,-44],[167,-46],[171,-42]],
    madagascar:[[43,-12],[50,-15],[47,-25],[44,-20]],
    philippines:[[120,18],[124,18],[126,10],[122,6],[120,13]],
    sriLanka:  [[80,10],[82,7],[80,6]],
    cuba:      [[-85,22],[-77,23],[-74,20],[-83,21]],
    hispaniola:[[-74,20],[-68,19],[-69,18],[-74,18]],
    taiwan:    [[120,25],[122,25],[121,22]],
    sakhalin:  [[142,54],[143,50],[142,46],[141,50]],
    novaya:    [[52,71],[62,74],[68,76],[58,74]],
    svalbard:  [[11,77],[22,79],[20,80],[12,79]],
    tasmania:  [[145,-41],[148,-41],[148,-43],[145,-43]],
    hokkaidoN: [[141,45],[145,44],[144,43],[141,43]]
  };

  /* Seas fully enclosed by a land ring above. Ray casting has no notion of
   * holes, so these are subtracted from the result instead. */
  var SEA = {
    black:      [[28,41],[40,42],[41,45],[33,46],[28,45]],
    caspian:    [[47,37],[54,41],[53,46],[49,45],[47,42]],
    baltic:     [[13,54],[21,56],[25,60],[19,63],[17,58],[12,56]],
    hudson:     [[-95,58],[-78,58],[-77,63],[-88,65],[-95,62]],
    greatLakes: [[-92,47],[-76,44],[-79,42],[-88,41]]
  };

  /* Antarctica is a ring around the pole rather than a blob on the map, so a
   * latitude cutoff describes it better than a polygon would. The peninsula
   * reaching up toward South America is the one part worth spelling out. */
  function isAntarctica(lon, lat) {
    if (lat < -71) return true;
    if (lat < -63 && lon > -65 && lon < -57) return true; // Antarctic Peninsula
    return false;
  }

  /* Ray casting in lon/lat space. None of the rings above cross the
   * antimeridian, so plain planar point-in-polygon is safe here. */
  function inRing(ring, lon, lat) {
    var inside = false;
    for (var i = 0, j = ring.length - 1; i < ring.length; j = i++) {
      var xi = ring[i][0], yi = ring[i][1];
      var xj = ring[j][0], yj = ring[j][1];
      if ((yi > lat) !== (yj > lat) &&
          lon < (xj - xi) * (lat - yi) / (yj - yi) + xi) {
        inside = !inside;
      }
    }
    return inside;
  }

  function isLand(lon, lat) {
    if (isAntarctica(lon, lat)) return true;
    var hit = false, key;
    for (key in LAND) {
      if (Object.prototype.hasOwnProperty.call(LAND, key) &&
          inRing(LAND[key], lon, lat)) { hit = true; break; }
    }
    if (!hit) return false;
    for (key in SEA) {
      if (Object.prototype.hasOwnProperty.call(SEA, key) &&
          inRing(SEA[key], lon, lat)) return false;
    }
    return true;
  }

  root.HollWorld = { LAND: LAND, SEA: SEA, isLand: isLand };
})(typeof window !== 'undefined' ? window : globalThis);

if (typeof module !== 'undefined' && module.exports) {
  module.exports = (typeof window !== 'undefined' ? window : globalThis).HollWorld;
}
