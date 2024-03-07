# Search ASF for SLCs and create a matrix job mapping for burst pairs
import asf_search as asf
import fsspec
import geopandas as gpd
import json
import os

# Parse Workflow inputs from environment variables
POL = os.environ['Polarization']
FULLBURSTID = os.environ['BurstId']

# If we're doing offset pairs DT is set in workflow (could also read GitHub context vars)
try:
    DT = int(os.environ['Offsets_DT'])
    START = "2017-01-01"
    END = None
except:
    NPAIRS = int(os.environ['NPairs'])
    START_YEAR = int(os.environ['Year'])
    START = f"{START_YEAR}-01-01",
    END = f"{START_YEAR+1}-03-01"
    DT = None

RELORB,BURSTID,SUBSWATH = FULLBURSTID.split('_')
print(RELORB,BURSTID,SUBSWATH)

# Get centroid of burst from database 
url = 'https://github.com/relativeorbit/s1burstids/raw/main/burst_map_IW_000001_375887_brotli.parquet'
with fsspec.open(url) as file:
    gfb = gpd.read_parquet(file,
                            filters=[('burst_id', '=', int(BURSTID)),
                                    ('subswath_name', '=', SUBSWATH)]
                            )
print(gfb)

# Search for SLCs
results = asf.search(platform=[asf.PLATFORM.SENTINEL1], 
                    processingLevel=asf.PRODUCT_TYPE.SLC, 
                    beamMode=asf.BEAMMODE.IW,
                    intersectsWith=gfb.iloc[0].geometry.centroid.wkt,
                    relativeOrbit=int(RELORB),
                    start=START,
                    end=END, #march to ensure we get some overlapping coverage for each year
                    )
gf = gpd.GeoDataFrame.from_features(results.geojson(), crs=4326)
print('Results:', len(gf))

# For case of frame overlap, ensure SLCs contain full burst
def get_overlap_area(gf, gfREF):
    frame_area = gfREF.iloc[0].geometry.area
    overlaps = gf.geometry.map(lambda x: x.intersection(gfREF.geometry.iloc[0]).area/frame_area)

    return overlaps

gf['overlap'] = get_overlap_area(gf, gfb)
gf = gf.query('overlap >= 0.80').reset_index(drop=True)

# Sort chronological ascending
gf['datetime'] = gpd.pd.to_datetime(gf.startTime)
gf = gf.sort_values(by='datetime', ignore_index=True)

print('Number of Acquisitions: ', len(gf))
burstIDs = gf.sceneName.to_list()
print('\n'.join(burstIDs))

pairs = []
if DT:
    # OFFSET PAIRS
    gf.set_index('datetime', inplace=True, drop=False)
    for index,row in gf.iterrows():
        dt = gf.index[-1] - index
        if dt < gpd.pd.Timedelta(days=365*DT):
            print(f'{refname} within {DT} years of last acquisition')
            break
        else:
            refname = row.sceneName
            ts = index + gpd.pd.DateOffset(years=DT)
            idx = gf.index.get_indexer([ts], method='nearest')[0]
            sec = gf.iloc[idx]
            secname = sec.sceneName
            shortname = f'{refname[17:25]}_{secname[17:25]}'
            pairs.append({'reference': refname, 'secondary': secname, 'name':shortname})
else:
    # InSAR Pairs
    idx_end_of_year = gf.index[gf.datetime.dt.year == START_YEAR][-1]
    for r in range(idx_end_of_year + 1):
        for s in range(1, NPAIRS + 1 ):
            try:
                ref = burstIDs[r]
                sec = burstIDs[r+s]
                shortname = f'{ref[17:25]}_{sec[17:25]}'
                pairs.append({'reference': ref, 'secondary': sec, 'name':shortname})
            except IndexError as e:
                print(f'ASF Search did not return a n+{s} pair for {ref}')

# Save JSON for GitHub Actions Matrix Job
matrixJSON = f'{{"include":{json.dumps(pairs)}}}'
print(f'Number of Interferograms: {len(pairs)}')
print(matrixJSON)

with open(os.environ['GITHUB_OUTPUT'], 'a') as f:
    print(f'BURST_IDS={burstIDs}', file=f)
    print(f'MATRIX_PARAMS_COMBINATIONS={matrixJSON}', file=f)
