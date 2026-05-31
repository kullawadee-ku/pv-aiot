# =====================================================================
# pv_plant_simuation_engine.py  —  PV-IoT Simulation Engine
# 
# Kullawadee Somboonviwat (kullawadee.som@ku.th)
# 
# G-SET Research Unit
# Faculty of Engineering at Sriracha, Kasetsart University
# 
# https://www.g-set.education
# Version : 1.0.0
# License : MIT
# =====================================================================
from datetime import datetime, timedelta
import csv
import math
import random
import matplotlib.pyplot as plt

# =====================================================================
# 🌦️ SEASON PRESETS  (Bangkok-calibrated, meteorologically grounded)
# =====================================================================
class SeasonPreset:
    """
    Bangkok three-season parameter presets based on TMD climatology data.

    ┌──────────────┬────────────────────────────────────────────────────┐
    │ SUMMER       │ Mar–May  Hot-dry season. Intense direct beam,      │
    │ (HOT-DRY)    │ low cloud, very high temps (35–40°C peak),         │
    │              │ calm wind. PV output high but thermal loss cuts it.│
    ├──────────────┼────────────────────────────────────────────────────┤
    │ RAINY        │ Jun–Oct  Monsoon season. Heavy persistent cloud,   │
    │ (MONSOON)    │ frequent afternoon convective storms, strong gusts, │
    │              │ moderate temps. GHI drops 40–60% vs summer.        │
    ├──────────────┼────────────────────────────────────────────────────┤
    │ WINTER       │ Nov–Feb  Cool-dry/NE monsoon. Mostly clear skies,  │
    │ (COOL-DRY)   │ low humidity, comfortable temps (25–32°C),         │
    │              │ moderate NE wind. Best PV efficiency of the year.  │
    └──────────────┴────────────────────────────────────────────────────┘

    Physics notes per season
    ────────────────────────
    SUMMER
    • High clearsky_a (extraterrestrial radiation near equinox peak)
    • Low cloud_mean (0.20) — mostly clear skies, intermittent convective clouds
    • High temp_base (33°C) + large amplitude (7°C) → cells hit 60–70°C → thermal loss dominates
    • Low wind (1.8 m/s) → poor panel cooling → further thermal derating

    RAINY
    • Moderate clearsky_a (slightly lower solar angle post-equinox)
    • High cloud_mean (0.70) — persistent stratiform + convective cloud
    • Low cloud_persistence (0.85) — clouds shift rapidly during squalls
    • Moderate temp (30°C) but high wind gusts (3.5 m/s) keep cells cooler → partially offsets GHI loss
    • Higher load_peak from air conditioning running against humidity

    WINTER
    • Lower clearsky_a (sun at lower declination for northern hemisphere effect)
    • Very low cloud_mean (0.15) — NE trade winds bring dry continental air
    • Low temp_base (26°C), small amplitude (4°C) → cells run cool → best efficiency
    • Moderate wind (3.0 m/s) from NE monsoon → good convective cooling
    • Lower building load (less A/C demand)
    """

    # Representative reference dates (used for solar geometry via day-of-year)
    SEASON_DATES = {
        'summer': datetime(2026, 4, 15),   # mid-April: hottest, clearest
        'rainy':  datetime(2026, 8, 15),   # mid-August: peak monsoon
        'winter': datetime(2026, 1, 15),   # mid-January: coolest, driest
    }

    # ── BASE (shared hardware / location / TOU — unchanged across seasons) ──
    _BASE = {
        'time_resolution_mins':        5.0,
        'latitude_deg':               13.75,
        'longitude_deg':             100.52,
        'timezone_offset_h':           7.0,
        'min_irradiance_threshold_wm2': 10.0,
        'cloud_beam_fraction_min':      0.05,
        'cloud_diffuse_max_factor':     1.3,
        'faiman_u0':                   25.0,
        'faiman_u1':                    6.84,
        'temp_noise_std_c':             0.25,
        'solar_thermal_coeff':          0.003,
        'load_peak1_hour':              8.0,
        'load_peak2_hour':             19.0,
        'load_shape1_std':              2.0,
        'load_shape2_std':              2.5,
        'load_noise_std_kw':            0.05,
        'load_lpf_alpha':               0.75,
        'area':                        27.78,
        'eta_stc':                      0.18,
        'temp_coeff_power':            -0.004,
        'stc_ref_cell_temp_c':         25.0,
        'stc_ref_irradiance_wm2':    1000.0,
        'tou_on_peak_rate':             4.18,
        'tou_off_peak_rate':            2.60,
        'on_peak_start_hour':           9.0,
        'on_peak_end_hour':            22.0,
    }

    # ── SEASON-SPECIFIC OVERRIDES ────────────────────────────────────
    _OVERRIDES = {

        # ════════════════════════════════════════════════════════════
        # ☀️  SUMMER  (Hot-Dry, Mar–May)
        # ════════════════════════════════════════════════════════════
        'summer': {
            # Atmosphere: near-equinox, clean dry air → high beam
            'clearsky_a':          1160.0,   # W/m² (high extraterrestrial near equinox)
            'clearsky_b':          0.160,    # low extinction (dry, low aerosol)
            'clearsky_c':          0.080,    # low diffuse fraction (clean sky)
            # Cloud: sparse cumulus, occasional afternoon towering Cu
            'cloud_cover_init':    0.20,
            'cloud_persistence':   0.90,     # slower evolution (stable anticyclone)
            'cloud_mean':          0.20,     # mostly clear
            'cloud_noise_std':     0.06,
            # Temperature: very hot
            'temp_base_c':        33.0,      # Bangkok Apr mean ~33°C
            'temp_amplitude_c':    7.0,      # large diurnal swing in dry air
            'temp_peak_hour':     14.5,
            # Wind: light and variable (calm season)
            'wind_speed_mean_ms':  1.8,
            'wind_speed_std_ms':   0.5,
            # Building load: high A/C demand due to extreme heat
            'base_load':           0.15,
            'peak_load':           2.8,      # A/C running hard all day
        },

        # ════════════════════════════════════════════════════════════
        # 🌧️  RAINY  (Monsoon, Jun–Oct)
        # ════════════════════════════════════════════════════════════
        'rainy': {
            # Atmosphere: post-equinox, high humidity & aerosol load
            'clearsky_a':          1100.0,   # slightly lower (sun angle + haze)
            'clearsky_b':          0.220,    # high extinction (humidity, aerosols)
            'clearsky_c':          0.120,    # more diffuse (scattering)
            # Cloud: persistent stratocumulus + afternoon convective squalls
            'cloud_cover_init':    0.70,
            'cloud_persistence':   0.85,     # lower — squalls shift cloud rapidly
            'cloud_mean':          0.70,     # heavily overcast most of the day
            'cloud_noise_std':     0.10,     # higher variance from squall lines
            # Temperature: warm but not extreme (cloud shading + evaporation)
            'temp_base_c':        30.5,
            'temp_amplitude_c':    4.5,      # small swing (cloud damps radiation)
            'temp_peak_hour':     14.0,
            # Wind: SW monsoon with gusty squalls
            'wind_speed_mean_ms':  3.5,
            'wind_speed_std_ms':   1.4,      # high variance from gusts
            # Building load: moderate; humidity keeps A/C running, but cloud blocks heat
            'base_load':           0.12,
            'peak_load':           2.4,
        },

        # ════════════════════════════════════════════════════════════
        # 🌬️  WINTER  (Cool-Dry, Nov–Feb)
        # ════════════════════════════════════════════════════════════
        'winter': {
            # Atmosphere: NE monsoon brings clean dry continental air
            'clearsky_a':          1100.0,   # lower extraterrestrial (lower solar angle)
            'clearsky_b':          0.155,    # very low extinction (clean dry air)
            'clearsky_c':          0.070,    # low diffuse (clear sky)
            # Cloud: minimal — NE monsoon suppresses convection
            'cloud_cover_init':    0.12,
            'cloud_persistence':   0.94,     # very stable clear-sky days
            'cloud_mean':          0.15,
            'cloud_noise_std':     0.05,
            # Temperature: coolest of the year
            'temp_base_c':        26.5,      # Bangkok Jan mean ~26°C
            'temp_amplitude_c':    4.0,      # moderate swing
            'temp_peak_hour':     14.0,
            # Wind: steady NE trade wind — best panel cooling
            'wind_speed_mean_ms':  3.0,
            'wind_speed_std_ms':   0.7,
            # Building load: lowest A/C demand
            'base_load':           0.08,
            'peak_load':           1.6,
        },
    }

    @classmethod
    def get(cls, season: str) -> dict:
        """
        Returns a fully merged parameter dict for the given season.
        Season key: 'summer' | 'rainy' | 'winter'
        """
        season = season.lower()
        if season not in cls._OVERRIDES:
            raise ValueError(f"Unknown season '{season}'. Choose from: {list(cls._OVERRIDES.keys())}")
        merged = {**cls._BASE, **cls._OVERRIDES[season]}
        return merged

    @classmethod
    def get_reference_date(cls, season: str) -> datetime:
        return cls.SEASON_DATES[season.lower()]

    @classmethod
    def list_seasons(cls) -> list:
        return list(cls._OVERRIDES.keys())


# =====================================================================
# ⚙️ CORE ENGINE: Physics-Accurate Telemetry Generator
# =====================================================================
class TelemetryGenerator:
    """
    Physics-accurate PV-IoT simulation engine.

    Physics model summary:
      Irradiance  : ASHRAE clear-sky (Spencer declination, Kasten-Young air mass)
      Cloud       : Markov mean-reverting persistence model
      Cell Temp   : Faiman model (PVGIS standard) — wind-aware
      Ambient T   : Sinusoidal diurnal with Gaussian noise
      Load        : Dual-Gaussian + first-order low-pass filter
      PV Output   : Temperature-corrected efficiency with irradiance threshold
    """

    def __init__(self, **params):
        self.time_resolution_mins = params.get('time_resolution_mins', 15.0)
        self.time_step_hours      = self.time_resolution_mins / 60.0

        self.latitude_deg      = params.get('latitude_deg',  13.75)
        self.longitude_deg     = params.get('longitude_deg', 100.52)
        self.timezone_offset_h = params.get('timezone_offset_h', 7.0)

        self.clearsky_a = params.get('clearsky_a', 1160.0)
        self.clearsky_b = params.get('clearsky_b', 0.174)
        self.clearsky_c = params.get('clearsky_c', 0.095)
        self.min_irradiance_threshold_wm2 = params.get('min_irradiance_threshold_wm2', 10.0)

        self.cloud_cover               = params.get('cloud_cover_init', 0.3)
        self.cloud_persistence         = params.get('cloud_persistence', 0.92)
        self.cloud_mean                = params.get('cloud_mean', 0.35)
        self.cloud_noise_std           = params.get('cloud_noise_std', 0.08)
        self.cloud_beam_fraction_min   = params.get('cloud_beam_fraction_min', 0.05)
        self.cloud_diffuse_max_factor  = params.get('cloud_diffuse_max_factor', 1.3)

        self.temp_base_c         = params.get('temp_base_c', 28.0)
        self.temp_amplitude_c    = params.get('temp_amplitude_c', 5.0)
        self.temp_peak_hour      = params.get('temp_peak_hour', 14.0)
        self.temp_noise_std_c    = params.get('temp_noise_std_c', 0.3)
        self.solar_thermal_coeff = params.get('solar_thermal_coeff', 0.004)

        self.wind_speed_mean_ms = params.get('wind_speed_mean_ms', 2.5)
        self.wind_speed_std_ms  = params.get('wind_speed_std_ms', 0.8)
        self.faiman_u0          = params.get('faiman_u0', 25.0)
        self.faiman_u1          = params.get('faiman_u1', 6.84)

        self.tou_on_peak_rate   = params.get('tou_on_peak_rate',  4.18)
        self.tou_off_peak_rate  = params.get('tou_off_peak_rate', 2.60)
        self.on_peak_start_hour = params.get('on_peak_start_hour', 9.0)
        self.on_peak_end_hour   = params.get('on_peak_end_hour',  22.0)

        self.base_load          = params.get('base_load', 0.1)
        self.peak_load          = params.get('peak_load', 2.0)
        self.load_peak1_hour    = params.get('load_peak1_hour', 8.0)
        self.load_peak2_hour    = params.get('load_peak2_hour', 19.0)
        self.load_shape1_std    = params.get('load_shape1_std', 2.0)
        self.load_shape2_std    = params.get('load_shape2_std', 2.5)
        self.load_noise_std_kw  = params.get('load_noise_std_kw', 0.05)
        self.load_lpf_alpha     = params.get('load_lpf_alpha', 0.75)
        self.last_building_load = self.base_load

        self.area             = params.get('area', 27.78)
        self.eta_stc          = params.get('eta_stc', 0.18)
        self.temp_coeff_power = params.get('temp_coeff_power', -0.004)
        self.stc_ref_cell_temp_c    = params.get('stc_ref_cell_temp_c', 25.0)
        self.stc_ref_irradiance_wm2 = params.get('stc_ref_irradiance_wm2', 1000.0)

    # ── Solar Geometry ───────────────────────────────────────────────
    def _solar_geometry(self, dt: datetime) -> dict:
        doy = dt.timetuple().tm_yday
        B = (2 * math.pi / 365) * (doy - 1)
        declination = (0.006918
                       - 0.399912 * math.cos(B) + 0.070257 * math.sin(B)
                       - 0.006758 * math.cos(2*B) + 0.000907 * math.sin(2*B)
                       - 0.002697 * math.cos(3*B) + 0.00148  * math.sin(3*B))
        eot = 229.18 * (0.000075
                        + 0.001868 * math.cos(B)  - 0.032077 * math.sin(B)
                        - 0.014615 * math.cos(2*B) - 0.04089  * math.sin(2*B))
        solar_time = (dt.hour + dt.minute / 60.0
                      + (self.longitude_deg - 15 * self.timezone_offset_h) / 15
                      + eot / 60.0)
        hour_angle = math.radians(15.0 * (solar_time - 12.0))
        lat_rad    = math.radians(self.latitude_deg)
        cos_zen    = max(0.0,
                         math.sin(lat_rad) * math.sin(declination)
                         + math.cos(lat_rad) * math.cos(declination) * math.cos(hour_angle))
        if cos_zen < 1e-4:
            return {'cos_zenith': 0.0, 'beam_wm2': 0.0, 'diffuse_wm2': 0.0, 'ghi_wm2': 0.0}
        zenith_deg = math.degrees(math.acos(cos_zen))
        air_mass   = max(1.0, 1.0 / (cos_zen + 0.50572 * (96.07995 - zenith_deg) ** -1.6364))
        beam_n     = self.clearsky_a * math.exp(-self.clearsky_b * air_mass)
        beam_h     = beam_n * cos_zen
        diffuse    = self.clearsky_c * beam_n
        return {'cos_zenith': cos_zen, 'beam_wm2': beam_h,
                'diffuse_wm2': diffuse, 'ghi_wm2': beam_h + diffuse}

    # ── Cloud Model ──────────────────────────────────────────────────
    def _update_cloud_cover(self):
        shock = random.gauss(0.0, self.cloud_noise_std)
        self.cloud_cover = max(0.0, min(1.0,
            self.cloud_persistence * self.cloud_cover
            + (1 - self.cloud_persistence) * self.cloud_mean
            + shock))

    def _apply_cloud_to_irradiance(self, beam: float, diffuse: float) -> float:
        bt = (1.0 - self.cloud_cover) + self.cloud_beam_fraction_min * self.cloud_cover
        df = 1.0 + (self.cloud_diffuse_max_factor - 1.0) * math.sin(math.pi * self.cloud_cover)
        df *= (1.0 - 0.7 * self.cloud_cover)
        return round(max(0.0, beam * bt + diffuse * max(0.1, df)), 1)

    # ── Ambient Temperature ──────────────────────────────────────────
    def _ambient_temperature(self, hour: float, irradiance: float) -> float:
        angle  = (hour - self.temp_peak_hour) * (math.pi / 12.0) + (math.pi / 2.0)
        return round(
            self.temp_base_c
            + self.temp_amplitude_c * math.sin(angle)
            + self.solar_thermal_coeff * irradiance
            + random.gauss(0.0, self.temp_noise_std_c), 1)

    # ── Cell Temperature (Faiman) ────────────────────────────────────
    def _cell_temperature(self, irradiance: float, t_amb: float, wind: float) -> float:
        if irradiance <= 0:
            return t_amb
        return round(t_amb + irradiance / (self.faiman_u0 + self.faiman_u1 * wind), 2)

    # ── PV Power ─────────────────────────────────────────────────────
    def calculate_solar_pv(self, irradiance: float, t_amb: float, wind: float) -> float:
        if irradiance < self.min_irradiance_threshold_wm2:
            return 0.0
        t_cell = self._cell_temperature(irradiance, t_amb, wind)
        tf     = 1.0 + self.temp_coeff_power * (t_cell - self.stc_ref_cell_temp_c)
        return round(max(0.0,
            self.area * self.eta_stc * (irradiance / self.stc_ref_irradiance_wm2) * tf), 3)

    # ── Building Load ────────────────────────────────────────────────
    def calculate_building_load(self, hour: float) -> float:
        s1 = math.exp(-((hour - self.load_peak1_hour)**2) / (2 * self.load_shape1_std**2))
        s2 = math.exp(-((hour - self.load_peak2_hour)**2) / (2 * self.load_shape2_std**2))
        target = max(self.base_load,
                     self.base_load + (s1 * 0.6 + s2) * (self.peak_load - self.base_load)
                     + random.gauss(0.0, self.load_noise_std_kw))
        smoothed = self.load_lpf_alpha * self.last_building_load + (1 - self.load_lpf_alpha) * target
        self.last_building_load = smoothed
        return round(max(self.base_load, smoothed), 3)

    # ── TOU Tariff ───────────────────────────────────────────────────
    def get_tou_rate(self, dt: datetime) -> float:
        if dt.weekday() >= 5:
            return self.tou_off_peak_rate
        h = dt.hour + dt.minute / 60.0
        return self.tou_on_peak_rate if self.on_peak_start_hour <= h < self.on_peak_end_hour else self.tou_off_peak_rate

    # ── Grid Interaction ─────────────────────────────────────────────
    def calculate_grid_interaction(self, pv: float, load: float, tou: float) -> dict:
        gkw  = max(0.0, load - pv)
        gkwh = gkw * self.time_step_hours
        return {'grid_power_kw': round(gkw, 3),
                'grid_energy_kwh': round(gkwh, 3),
                'cost_thb': round(gkwh * tou, 3)}


# =====================================================================
# 🛠️ SIMULATION RUNNER
# =====================================================================
def simulate_time_range(generator: TelemetryGenerator,
                        start_date: datetime, end_date: datetime,
                        season_label: str = '') -> list:
    dataset = []
    current = start_date
    dt_step = timedelta(minutes=generator.time_resolution_mins)
    generator.last_building_load = generator.calculate_building_load(0.0)
    label = f"[{season_label.upper()}] " if season_label else ""
    print(f"{label}Simulating {start_date.date()} → {end_date.date()} ...")

    while current <= end_date:
        hour = current.hour + current.minute / 60.0
        geo  = generator._solar_geometry(current)
        if geo['ghi_wm2'] > 0:
            generator._update_cloud_cover()
        irr  = generator._apply_cloud_to_irradiance(geo['beam_wm2'], geo['diffuse_wm2'])
        temp = generator._ambient_temperature(hour, irr)
        wind = max(0.1, random.gauss(generator.wind_speed_mean_ms, generator.wind_speed_std_ms))
        pv   = generator.calculate_solar_pv(irr, temp, wind)
        load = generator.calculate_building_load(hour)
        tou  = generator.get_tou_rate(current)
        grid = generator.calculate_grid_interaction(pv, load, tou)

        dataset.append({
            'timestamp':        current.strftime('%Y-%m-%d %H:%M:%S'),
            'season':           season_label,
            'hour':             round(hour, 2),
            'cloud_cover':      round(generator.cloud_cover, 3),
            'cos_zenith':       round(geo['cos_zenith'], 4),
            'irradiance_wm2':   irr,
            'ambient_temp_c':   temp,
            'wind_speed_ms':    round(wind, 2),
            'pv_generation_kw': pv,
            'building_load_kw': load,
            'grid_power_kw':    grid['grid_power_kw'],
            'grid_energy_kwh':  grid['grid_energy_kwh'],
            'tou_rate_thb':     tou,
            'cost_thb':         grid['cost_thb'],
        })
        current += dt_step

    print(f"  → {len(dataset)} data points generated.")
    return dataset


# =====================================================================
# 💾 EXPORT
# =====================================================================
def save_simulation_to_csv(dataset: list, filename: str = "simulation_output.csv"):
    if not dataset:
        return
    with open(filename, mode='w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=dataset[0].keys())
        writer.writeheader()
        writer.writerows(dataset)
    print(f"[+] CSV saved: '{filename}'")


# =====================================================================
# 📊 SINGLE-SEASON PLOT
# =====================================================================
def plot_single_season(dataset: list, season: str, save_img: str = None):
    ts     = [d['timestamp']        for d in dataset]
    irr    = [d['irradiance_wm2']   for d in dataset]
    temp   = [d['ambient_temp_c']   for d in dataset]
    cloud  = [d['cloud_cover']      for d in dataset]
    pv     = [d['pv_generation_kw'] for d in dataset]
    load   = [d['building_load_kw'] for d in dataset]
    grid   = [d['grid_power_kw']    for d in dataset]
    cost   = [d['cost_thb']         for d in dataset]

    SEASON_COLORS = {'summer': '#e07b39', 'rainy': '#4a90d9', 'winter': '#5aab7a'}
    color = SEASON_COLORS.get(season, 'tab:blue')

    fig, axes = plt.subplots(4, 1, figsize=(14, 16), sharex=True)
    titles = {
        'summer': '[HOT-DRY]  SUMMER — Apr representative day',
        'rainy':  '[MONSOON]  RAINY   — Aug representative day',
        'winter': '[COOL-DRY] WINTER  — Jan representative day',
    }
    fig.suptitle(f"Physics-Accurate PV Simulation: {titles.get(season, season.title())}",
                 fontsize=13, fontweight='bold')

    # Panel 1: Irradiance + Temperature
    ax1 = axes[0]
    ax1.fill_between(ts, irr, color=color, alpha=0.25)
    l1, = ax1.plot(ts, irr, color=color, lw=2, label='GHI (W/m²)')
    ax1.set_ylabel('Solar Irradiance (W/m²)', color=color, fontweight='bold')
    ax1.tick_params(axis='y', labelcolor=color)
    ax1b = ax1.twinx()
    l2, = ax1b.plot(ts, temp, color='tab:red', lw=2, ls='--', label='Ambient Temp (°C)')
    ax1b.set_ylabel('Temp (°C)', color='tab:red', fontweight='bold')
    ax1b.tick_params(axis='y', labelcolor='tab:red')
    ax1.legend([l1, l2], [l1.get_label(), l2.get_label()], loc='upper left')
    ax1.set_title("Weather Profile (ASHRAE Clear-Sky + Markov Cloud)", fontsize=10)
    ax1.grid(True, ls=':', alpha=0.5)

    # Panel 2: Cloud Cover
    axes[1].fill_between(ts, cloud, color='steelblue', alpha=0.4)
    axes[1].plot(ts, cloud, color='steelblue', lw=1.5)
    axes[1].set_ylim(0, 1.05)
    axes[1].set_ylabel('Cloud Cover (0–1)', fontweight='bold')
    axes[1].set_title("Markov Cloud Cover Evolution", fontsize=10)
    axes[1].grid(True, ls=':', alpha=0.5)

    # Panel 3: Energy Balance
    axes[2].plot(ts, load, color='tab:blue',  lw=2, label='Building Load (kW)')
    axes[2].plot(ts, pv,   color='tab:green', lw=2, label='PV Generation (kW)')
    axes[2].fill_between(ts, grid, color='tab:red', alpha=0.12)
    axes[2].plot(ts, grid, color='tab:red', lw=1.5, ls=':', label='Grid Import (kW)')
    axes[2].set_ylabel('Power (kW)', fontweight='bold')
    axes[2].set_title("Energy Balance (Faiman Cell Temp + LPF Load)", fontsize=10)
    axes[2].legend(loc='upper left')
    axes[2].grid(True, ls=':', alpha=0.5)

    # Panel 4: Cost
    axes[3].bar(ts, cost, width=0.6, color='darkred', alpha=0.6)
    axes[3].set_ylabel('Cost (THB/slot)', fontweight='bold')
    axes[3].set_xlabel('Time', fontweight='bold')
    axes[3].set_title("TOU Electricity Cost", fontsize=10)
    axes[3].grid(True, ls=':', alpha=0.5)

    n = len(ts)
    step = max(1, n // 8)
    axes[3].set_xticks(range(0, n, step))
    axes[3].set_xticklabels([ts[i] for i in range(0, n, step)], rotation=15, ha='right')

    plt.tight_layout()
    if save_img:
        plt.savefig(save_img, dpi=150)
        print(f"[+] Saved: '{save_img}'")
    plt.show()


# =====================================================================
# 📊 SEASONAL COMPARISON PLOT  (all 3 seasons overlaid)
# =====================================================================
def plot_season_comparison(season_datasets: dict, save_img: str = None):
    """
    Overlays summer / rainy / winter on the same axes for direct comparison.
    season_datasets = {'summer': [...], 'rainy': [...], 'winter': [...]}
    """
    COLORS = {'summer': '#e07b39', 'rainy': '#4a90d9', 'winter': '#5aab7a'}
    LABELS = {'summer': '[S] Summer (Hot-Dry)', 'rainy': '[R] Rainy (Monsoon)', 'winter': '[W] Winter (Cool-Dry)'}

    # Use hour axis (0–24) for overlay, regardless of calendar date
    def hours(ds): return [d['hour'] for d in ds]

    fig, axes = plt.subplots(4, 1, figsize=(14, 16), sharex=True)
    fig.suptitle("Bangkok PV System — Three-Season Comparison (Representative Day)",
                 fontsize=13, fontweight='bold')

    metrics = [
        ('irradiance_wm2',   'Solar Irradiance (W/m²)',  'Weather: GHI'),
        ('ambient_temp_c',   'Ambient Temp (°C)',         'Temperature Profile'),
        ('pv_generation_kw', 'PV Generation (kW)',        'PV Output vs Building Load'),
        ('cost_thb',         'Cost (THB/slot)',            'TOU Electricity Cost'),
    ]

    for ax, (key, ylabel, title) in zip(axes, metrics):
        for season, ds in season_datasets.items():
            h = hours(ds)
            y = [d[key] for d in ds]
            ax.plot(h, y, color=COLORS[season], lw=2, label=LABELS[season], alpha=0.85)
            if key == 'pv_generation_kw':
                # Also show load as dashed line (same color, dashed)
                y_load = [d['building_load_kw'] for d in ds]
                ax.plot(h, y_load, color=COLORS[season], lw=1.2, ls='--', alpha=0.5)

        ax.set_ylabel(ylabel, fontweight='bold')
        ax.set_title(title, fontsize=10)
        ax.legend(loc='upper left', fontsize=9)
        ax.grid(True, ls=':', alpha=0.5)

    axes[-1].set_xlabel('Hour of Day', fontweight='bold')
    axes[-1].set_xticks(range(0, 25, 2))

    # Add note about dashed lines in PV panel
    axes[2].annotate("(dashed = building load)", xy=(0.72, 0.92),
                     xycoords='axes fraction', fontsize=8, color='gray')

    plt.tight_layout()
    if save_img:
        plt.savefig(save_img, dpi=150)
        print(f"[+] Comparison plot saved: '{save_img}'")
    plt.show()


# =====================================================================
# 📋 FINANCIAL SUMMARY
# =====================================================================
def get_financial_summary(season: str, dataset: list) -> dict:
    """
    Calculate and return financial/energy summary as a dict.
    No side effects — does not print anything.

    Returns
    -------
    dict with keys:
        season, avg_irradiance_wm2, avg_temp_c, peak_pv_kw,
        total_pv_kwh, total_grid_kwh, total_cost_thb

    Example
    -------
    s = get_financial_summary('summer', data)
    payback = 180_000 / s['total_cost_thb'] / 365
    """
    total_grid_kwh = sum(d['grid_energy_kwh']              for d in dataset)
    total_cost_thb = sum(d['cost_thb']                     for d in dataset)
    total_pv_kwh   = sum(d['pv_generation_kw'] * (5/60)   for d in dataset)
    avg_irr        = sum(d['irradiance_wm2']               for d in dataset) / len(dataset)
    avg_temp       = sum(d['ambient_temp_c']               for d in dataset) / len(dataset)
    peak_pv_kw     = max(d['pv_generation_kw']             for d in dataset)

    return {
        'season':             season,
        'avg_irradiance_wm2': round(avg_irr,       1),
        'avg_temp_c':         round(avg_temp,       1),
        'peak_pv_kw':         round(peak_pv_kw,     3),
        'total_pv_kwh':       round(total_pv_kwh,   2),
        'total_grid_kwh':     round(total_grid_kwh, 2),
        'total_cost_thb':     round(total_cost_thb, 2),
    }


def print_financial_summary(season: str, dataset: list) -> None:
    """
    Print a formatted financial summary to stdout.
    For downstream calculations, use get_financial_summary() instead.

    Example
    -------
    print_financial_summary('summer', data)   # human-readable output
    s = get_financial_summary('summer', data) # machine-readable dict
    """
    s = get_financial_summary(season, dataset)
    print(f"\n{'='*62}")
    print(f"  {s['season'].upper()} SEASON — DAILY FINANCIAL SUMMARY")
    print(f"{'='*62}")
    print(f"  Avg Solar Irradiance   : {s['avg_irradiance_wm2']:>8.1f} W/m²")
    print(f"  Avg Ambient Temp       : {s['avg_temp_c']:>8.1f} °C")
    print(f"  Peak PV Output         : {s['peak_pv_kw']:>8.3f} kW")
    print(f"  Total PV Generation    : {s['total_pv_kwh']:>8.2f} kWh")
    print(f"  Total Grid Import      : {s['total_grid_kwh']:>8.2f} kWh")
    print(f"  Total TOU Cost         : {s['total_cost_thb']:>8.2f} THB")
    print(f"{'='*62}")


# =====================================================================
# 🎲 REPRODUCIBILITY
# =====================================================================
def set_seed(seed: int = 42) -> None:
    """
    Fix the random seed for fully reproducible simulation runs.
    Call this once at the top of your notebook before any run_season() call.

    Example
    -------
    set_seed(42)
    data = run_season('summer')   # every learner gets identical output
    """
    random.seed(seed)
    print(f"[seed={seed}] Random seed fixed — results are now reproducible.")


# =====================================================================
# 🚀 CONVENIENCE RUNNER  (call this from your notebook)
# =====================================================================
def run_season(season: str, time_resolution_mins: float = 5.0, **override_params) -> list:
    """
    Convenience function: build engine from a SeasonPreset and simulate one full day.

    Parameters
    ----------
    season               : 'summer' | 'rainy' | 'winter'
    time_resolution_mins : time step in minutes (default 5)
    **override_params    : any SeasonPreset parameter to override, e.g. cloud_mean=0.8

    Returns
    -------
    list of dicts — one entry per time step

    Example (Colab)
    ---------------
    data = run_season('summer')
    plot_single_season(data, 'summer')
    print_financial_summary('summer', data)
    """
    params = SeasonPreset.get(season)
    params['time_resolution_mins'] = time_resolution_mins
    params.update(override_params)                         # apply any overrides
    engine = TelemetryGenerator(**params)
    ref    = SeasonPreset.get_reference_date(season)
    start  = ref.replace(hour=0,  minute=0)
    end    = ref.replace(hour=23, minute=55)
    return simulate_time_range(engine, start, end, season_label=season)


# =====================================================================
# 📅 MULTI-DAY RUNNER
# =====================================================================
def run_days(season: str,
             n_days: int = 7,
             start_date: datetime = None,
             time_resolution_mins: float = 5.0,
             **override_params) -> list:
    """
    Simulate multiple consecutive days for a given season.

    The cloud cover state carries over between days (Markov continuity),
    so the simulation behaves as one continuous run — not n independent days.

    Parameters
    ----------
    season               : 'summer' | 'rainy' | 'winter'
    n_days               : number of days to simulate (default 7)
    start_date           : first day as datetime (default: season reference date)
    time_resolution_mins : time step in minutes (default 5)
    **override_params    : any SeasonPreset parameter to override

    Returns
    -------
    list of dicts — one entry per time step across all days

    Examples
    --------
    # 7-day summer simulation
    data = run_days('summer', n_days=7)
    save_simulation_to_csv(data, 'summer_7days.csv')

    # 14-day rainy season starting from a specific date
    data = run_days('rainy', n_days=14, start_date=datetime(2026, 8, 1))
    """
    params = SeasonPreset.get(season)
    params['time_resolution_mins'] = time_resolution_mins
    params.update(override_params)
    engine = TelemetryGenerator(**params)

    if start_date is None:
        start_date = SeasonPreset.get_reference_date(season).replace(hour=0, minute=0)
    else:
        start_date = start_date.replace(hour=0, minute=0)

    end_date = start_date + timedelta(days=n_days) - timedelta(minutes=time_resolution_mins)

    return simulate_time_range(engine, start_date, end_date, season_label=season)
