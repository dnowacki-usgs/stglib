from __future__ import division, print_function

import xarray as xr
import netCDF4
from ..core import utils
from . import qaqc

def cdf_to_nc(cdf_filename, atmpres=False):
    """
    Load a "raw" .cdf file and generate a processed .nc file
    """

    # Load raw .cdf data
    VEL = load_cdf(cdf_filename, atmpres=atmpres)

    # Clip data to in/out water times or via good_ens
    VEL = utils.clip_ds(VEL)

    # Create water_depth variables
    VEL = utils.create_water_depth(VEL)

    # Create depth variable depending on orientation
    VEL, T = qaqc.set_orientation(VEL, VEL['TransMatrix'].values)

    # Transform coordinates from, most likely, BEAM to ENU
    u, v, w = qaqc.coord_transform(VEL['VEL1'].values, VEL['VEL2'].values, VEL['VEL3'].values,
        VEL['Heading'].values, VEL['Pitch'].values, VEL['Roll'].values, T, VEL.attrs['AQDCoordinateSystem'])

    VEL['U'] = xr.DataArray(u, dims=('time', 'bindist'))
    VEL['V'] = xr.DataArray(v, dims=('time', 'bindist'))
    VEL['W'] = xr.DataArray(w, dims=('time', 'bindist'))

    VEL = qaqc.magvar_correct(VEL)

    VEL['AGC'] = (VEL['AMP1'] + VEL['AMP2'] + VEL['AMP3']) / 3

    VEL = qaqc.trim_vel(VEL)

    VEL = qaqc.make_bin_depth(VEL)

    # Reshape and associate dimensions with lat/lon
    for var in ['U', 'V', 'W', 'AGC', 'Pressure', 'Temperature', 'Heading', 'Pitch', 'Roll']:
        VEL = da_reshape(VEL, var)

    # swap_dims from bindist to depth
    VEL = ds_swap_dims(VEL)

    VEL = ds_rename(VEL)

    VEL = ds_drop(VEL)

    VEL = ds_add_attrs(VEL)

    VEL = utils.add_min_max(VEL)

    VEL = qaqc.add_delta_t(VEL)

    VEL = utils.add_start_stop_time(VEL)

    VEL = utils.add_epic_history(VEL)

    nc_filename = VEL.attrs['filename'] + '.nc'

    VEL.to_netcdf(nc_filename, unlimited_dims='time')
    print('Done writing netCDF file', nc_filename)

    # rename time variables after the fact to conform with EPIC/CMG standards
    utils.rename_time(nc_filename)

    print('Renamed dimensions')

    return VEL


def load_cdf(cdf_filename, atmpres=False):
    """
    Load raw .cdf file and, optionally, an atmospheric pressure .cdf file
    """

    ds = xr.open_dataset(cdf_filename, autoclose=True)

    if atmpres is not False:
        p = xr.open_dataset(atmpres, autoclose=True)
        # TODO: check to make sure this data looks OK
        # need to call load for waves; it's not in memory and throws error
        ds['Pressure_ac'] = xr.DataArray(ds['Pressure'].load() - (p['atmpres'] - p['atmpres'].offset))

    return ds


# TODO: add analog input variables (OBS, NTU, etc)


def ds_swap_dims(ds):

    ds = ds.swap_dims({'bindist': 'depth'})

    # need to swap dims and then reassign bindist to be a normal variable (no longer a coordinate)
    valbak = ds['bindist'].values
    ds = ds.drop('bindist')
    ds['bindist'] = xr.DataArray(valbak, dims='depth')

    return ds


def da_reshape(ds, var, waves=False):
    """
    Add lon and lat dimensions to DataArrays and reshape to conform to our
    standard order
    """

    # Add the dimensions using concat
    ds[var] = xr.concat([ds[var]], dim=ds['lon'])
    ds[var] = xr.concat([ds[var]], dim=ds['lat'])

    # Reshape using transpose depending on shape
    if waves == False:
        if len(ds[var].shape) == 4:
            ds[var] = ds[var].transpose('time', 'lon', 'lat', 'bindist')
        elif len(ds[var].shape) == 3:
            ds[var] = ds[var].transpose('time', 'lon', 'lat')

    return ds


def ds_rename(ds, waves=False):
    """
    Rename DataArrays within Dataset for EPIC compliance
    """

    varnames = {'Pressure': 'P_1',
        'Temperature': 'Tx_1211',
        'Heading': 'Hdg_1215',
        'Pitch': 'Ptch_1216',
        'Roll': 'Roll_1217'}

    if 'Pressure_ac' in ds:
        varnames['Pressure_ac'] = 'P_1ac'

    if waves == False:
        varnames.update({'U': 'u_1205',
            'V': 'v_1206',
            'W': 'w_1204',
            'AGC': 'AGC_1202'})
    elif waves == True:
        varnames.update({'VEL1': 'vel1_1277',
            'VEL2': 'vel2_1278',
            'VEL3': 'vel3_1279',
            'AMP1': 'AGC1_1221',
            'AMP2': 'AGC2_1222',
            'AMP3': 'AGC3_1223'})

    ds.rename(varnames, inplace=True)

    return ds


def ds_drop(ds):
    """
    Drop old DataArrays from Dataset that won't make it into the final .nc file
    """

    todrop = ['VEL1',
        'VEL2',
        'VEL3',
        'AMP1',
        'AMP2',
        'AMP3',
        'Battery',
        'TransMatrix',
        'AnalogInput1',
        'AnalogInput2',
        'jd',
        'Depth']

    ds = ds.drop(todrop)

    return ds


def ds_add_attrs(ds, waves=False):
    """
    add EPIC and CMG attributes to xarray Dataset
    """

    def add_vel_attributes(vel, dsattrs):
        vel.attrs.update({'units': 'cm/s',
            'data_cmnt': 'Velocity in shallowest bin is often suspect and should be used with caution'})

        # TODO: why do we only do trim_method for Water Level SL?
        if 'trim_method' in dsattrs and dsattrs['trim_method'].lower() == 'water level sl':
            vel.attrs.update({'note': 'Velocity bins trimmed if out of water or if side lobes intersect sea surface'})

    def add_attributes(var, dsattrs):
        var.attrs.update({'serial_number': dsattrs['AQDSerial_Number'],
            'initial_instrument_height': dsattrs['initial_instrument_height'],
            'nominal_instrument_depth': dsattrs['nominal_instrument_depth'],
            'height_depth_units': 'm',
            'sensor_type': dsattrs['INST_TYPE']})
        var.encoding['_FillValue'] = 1e35

    ds.attrs.update({'COMPOSITE': 0})

    # Update attributes for EPIC and STG compliance
    ds.lat.encoding['_FillValue'] = False
    ds.lon.encoding['_FillValue'] = False
    ds.depth.encoding['_FillValue'] = False
    ds.time.encoding['_FillValue'] = False
    ds.epic_time.encoding['_FillValue'] = False
    ds.epic_time2.encoding['_FillValue'] = False

    ds['time'].attrs.update({'standard_name': 'time',
        'axis': 'T'})

    ds['epic_time'].attrs.update({'units': 'True Julian Day',
        'type': 'EVEN',
        'epic_code': 624})

    ds['epic_time2'].attrs.update({'units': 'msec since 0:00 GMT',
        'type': 'EVEN',
        'epic_code': 624})

    ds['depth'].attrs.update({'units': 'm',
        'long_name': 'mean water depth',
        'initial_instrument_height': ds.attrs['initial_instrument_height'],
        'nominal_instrument_depth': ds.attrs['nominal_instrument_depth'],
        'epic_code': 3})

    if waves == False:
        ds['u_1205'].attrs.update({'name': 'u',
            'long_name': 'Eastward Velocity',
            'generic_name': 'u',
            'epic_code': 1205})

        ds['v_1206'].attrs.update({'name': 'v',
            'long_name': 'Northward Velocity',
            'generic_name': 'v',
            'epic_code': 1206})

        ds['w_1204'].attrs.update({'name': 'w',
            'long_name': 'Vertical Velocity',
            'generic_name': 'w',
            'epic_code': 1204})

        ds['AGC_1202'].attrs.update({'units': 'counts',
            'name': 'AGC',
            'long_name': 'Average Echo Intensity',
            'generic_name': 'AGC',
            'epic_code': 1202})

    elif waves == True:
        ds['vel1_1277'].attrs.update({'units': 'mm/s',
            'long_name': 'Beam 1 Velocity',
            'generic_name': 'vel1',
            'epic_code': 1277})

        ds['vel2_1278'].attrs.update({'units': 'mm/s',
            'long_name': 'Beam 2 Velocity',
            'generic_name': 'vel2',
            'epic_code': 1278})

        ds['vel3_1279'].attrs.update({'units': 'mm/s',
            'long_name': 'Beam 3 Velocity',
            'generic_name': 'vel3',
            'epic_code': 1279})

        ds['AGC1_1221'].attrs.update({'units': 'counts',
            'long_name': 'Echo Intensity (AGC) Beam 1',
            'generic_name': 'AGC1',
            'epic_code': 1221})

        ds['AGC2_1222'].attrs.update({'units': 'counts',
            'long_name': 'Echo Intensity (AGC) Beam 2',
            'generic_name': 'AGC2',
            'epic_code': 1222})

        ds['AGC3_1223'].attrs.update({'units': 'counts',
            'long_name': 'Echo Intensity (AGC) Beam 3',
            'generic_name': 'AGC3',
            'epic_code': 1223})

    ds['P_1'].attrs.update({'units': 'dbar',
        'name': 'P',
        'long_name': 'Pressure',
        'generic_name': 'depth',
        'epic_code': 1}) # TODO: is this generic name correct?

    if 'P_1ac' in ds:
        ds['P_1ac'].attrs.update({'units': 'dbar',
            'name': 'Pac',
            'long_name': 'Corrected pressure'})
        if 'P_1ac_note' in ds.attrs:
            ds['P_1ac'].attrs.update({'note': ds.attrs['P_1ac_note']})

        add_attributes(ds['P_1ac'], ds.attrs)

        ds.attrs['history'] = 'Atmospheric pressure compensated. ' + ds.attrs['history']

    ds['bin_depth'].attrs.update({'units': 'm',
        'name': 'bin depth'})

    if 'P_1ac' in ds:
        ds['bin_depth'].attrs.update({'note': 'Actual depth time series of velocity bins. Calculated as corrected pressure(P_1ac) - bindist.'})
    else:
        ds['bin_depth'].attrs.update({'note': 'Actual depth time series of velocity bins. Calculated as pressure(P_1) - bindist.'})

    ds['Tx_1211'].attrs.update({'units': 'C',
        'name': 'Tx',
        'long_name': 'Instrument Transducer Temperature',
        'generic_name': 'temp',
        'epic_code': 1211})

    ds['Hdg_1215'].attrs.update({'units': 'degrees',
        'name': 'Hdg',
        'long_name': 'Instrument Heading',
        'generic_name': 'hdg',
        'epic_code': 1215})

    if 'magnetic_variation_at_site' in ds.attrs:
        ds['Hdg_1215'].attrs.update({'note': 'Heading is degrees true. Converted from magnetic with magnetic variation of ' + str(ds.attrs['magnetic_variation_at_site'])})
    elif 'magnetic_variation' in ds.attrs:
        ds['Hdg_1215'].attrs.update({'note': 'Heading is degrees true. Converted from magnetic with magnetic variation of ' + str(ds.attrs['magnetic_variation'])})

    ds['Ptch_1216'].attrs.update({'units': 'degrees',
        'name': 'Ptch',
        'long_name': 'Instrument Pitch',
        'generic_name': 'ptch',
        'epic_code': 1216})

    ds['Roll_1217'].attrs.update({'units': 'degrees',
        'name': 'Roll',
        'long_name': 'Instrument Roll',
        'generic_name': 'roll',
        'epic_code': 1217})

    ds['bindist'].attrs.update({'units': 'm',
        'long_name': 'distance from transducer head',
        'blanking_distance': ds.attrs['AQDBlankingDistance'],
        'note': 'distance is along profile from instrument head to center of bin'})

    if waves == False:
        for v in ['AGC_1202', 'u_1205', 'v_1206', 'w_1204']:
            add_attributes(ds[v], ds.attrs)
        for v in ['u_1205', 'v_1206', 'w_1204']:
            add_vel_attributes(ds[v], ds.attrs)
    elif waves == True:
        for v in ['vel1_1277', 'vel2_1278', 'vel3_1279', 'AGC1_1221', 'AGC2_1222', 'AGC3_1223']:
            add_attributes(ds[v], ds.attrs)

    for v in ['P_1', 'Tx_1211', 'Hdg_1215', 'Ptch_1216', 'Roll_1217', 'bin_depth', 'bindist']:
        add_attributes(ds[v], ds.attrs)

    return ds
