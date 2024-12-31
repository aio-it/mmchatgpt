import json
from dataclasses import dataclass, fields
from datetime import datetime
from typing import Any, List, Optional


@dataclass
class IntervalsActivity:
    """
    Represents an activity from Intervals.icu API
    """
    id: str
    start_date_local: str
    type: str
    name: str
    start_date: str
    distance: Optional[float] = None
    moving_time: Optional[int] = None
    calories: Optional[int] = None
    average_speed: Optional[float] = None
    description: Optional[str] = None
    icu_ignore_time: Optional[bool] = None
    icu_pm_cp: Optional[float] = None
    icu_pm_w_prime: Optional[float] = None
    icu_pm_p_max: Optional[float] = None
    icu_pm_ftp: Optional[float] = None
    icu_pm_ftp_secs: Optional[int] = None
    icu_pm_ftp_watts: Optional[float] = None
    icu_ignore_power: Optional[bool] = None
    icu_rolling_cp: Optional[float] = None
    icu_rolling_w_prime: Optional[float] = None
    icu_rolling_p_max: Optional[float] = None
    icu_rolling_ftp: Optional[float] = None
    icu_rolling_ftp_delta: Optional[float] = None
    icu_training_load: Optional[float] = None
    icu_atl: Optional[float] = None
    icu_ctl: Optional[float] = None
    paired_event_id: Optional[str] = None
    icu_ftp: Optional[float] = None
    icu_joules: Optional[float] = None
    icu_recording_time: Optional[int] = None
    elapsed_time: Optional[int] = None
    icu_weighted_avg_watts: Optional[float] = None
    carbs_used: Optional[float] = None
    icu_distance: Optional[float] = None
    coasting_time: Optional[int] = None
    total_elevation_gain: Optional[float] = None
    timezone: Optional[str] = None
    trainer: Optional[bool] = None
    commute: Optional[bool] = None
    max_speed: Optional[float] = None
    device_watts: Optional[bool] = None
    has_heartrate: Optional[bool] = None
    max_heartrate: Optional[int] = None
    average_heartrate: Optional[float] = None
    average_cadence: Optional[float] = None
    average_temp: Optional[float] = None
    min_temp: Optional[float] = None
    max_temp: Optional[float] = None
    avg_lr_balance: Optional[float] = None
    gap: Optional[float] = None
    gap_model: Optional[str] = None
    use_elevation_correction: Optional[bool] = None
    race: Optional[bool] = None
    gear: Optional[str] = None
    perceived_exertion: Optional[float] = None
    device_name: Optional[str] = None
    power_meter: Optional[str] = None
    power_meter_serial: Optional[str] = None
    power_meter_battery: Optional[float] = None
    crank_length: Optional[float] = None
    external_id: Optional[str] = None
    file_sport_index: Optional[int] = None
    file_type: Optional[str] = None
    icu_athlete_id: Optional[str] = None
    created: Optional[str] = None
    icu_sync_date: Optional[str] = None
    analyzed: Optional[str] = None
    icu_w_prime: Optional[float] = None
    threshold_pace: Optional[float] = None
    icu_hr_zones: Optional[List[int]] = None
    pace_zones: Optional[List[float]] = None
    lthr: Optional[int] = None
    icu_resting_hr: Optional[int] = None
    icu_weight: Optional[float] = None
    icu_power_zones: Optional[List[int]] = None
    icu_sweet_spot_min: Optional[int] = None
    icu_sweet_spot_max: Optional[int] = None
    trimp: Optional[float] = None
    icu_warmup_time: Optional[int] = None
    icu_cooldown_time: Optional[int] = None
    icu_chat_id: Optional[str] = None
    icu_ignore_hr: Optional[bool] = None
    ignore_velocity: Optional[bool] = None
    ignore_pace: Optional[bool] = None
    ignore_parts: Optional[List[str]] = None
    stream_types: Optional[List[str]] = None
    has_weather: Optional[bool] = None
    has_segments: Optional[bool] = None
    power_field_names: Optional[List[str]] = None
    power_field: Optional[str] = None
    icu_zone_times: Optional[List[int]] = None
    icu_hr_zone_times: Optional[List[int]] = None
    pace_zone_times: Optional[List[float]] = None
    gap_zone_times: Optional[List[float]] = None
    use_gap_zone_times: Optional[bool] = None
    tiz_order: Optional[str] = None
    polarization_index: Optional[float] = None
    icu_achievements: Optional[List[str]] = None
    icu_intervals_edited: Optional[bool] = None
    lock_intervals: Optional[bool] = None
    icu_lap_count: Optional[int] = None
    icu_joules_above_ftp: Optional[float] = None
    icu_max_wbal_depletion: Optional[float] = None
    icu_hrr: Optional[float] = None
    icu_sync_error: Optional[str] = None
    icu_color: Optional[str] = None
    icu_power_hr_z2: Optional[float] = None
    icu_power_hr_z2_mins: Optional[float] = None
    icu_cadence_z2: Optional[float] = None
    icu_rpe: Optional[float] = None
    feel: Optional[str] = None
    kg_lifted: Optional[float] = None
    decoupling: Optional[float] = None
    icu_median_time_delta: Optional[float] = None
    p30s_exponent: Optional[float] = None
    workout_shift_secs: Optional[int] = None
    strava_id: Optional[str] = None
    lengths: Optional[int] = None
    pool_length: Optional[float] = None
    compliance: Optional[float] = None
    coach_tick: Optional[bool] = None
    source: Optional[str] = None
    oauth_client_id: Optional[str] = None
    oauth_client_name: Optional[str] = None
    average_altitude: Optional[float] = None
    min_altitude: Optional[float] = None
    max_altitude: Optional[float] = None
    power_load: Optional[float] = None
    hr_load: Optional[float] = None
    pace_load: Optional[float] = None
    hr_load_type: Optional[str] = None
    pace_load_type: Optional[str] = None
    tags: Optional[List[str]] = None
    attachments: Optional[List[str]] = None
    recording_stops: Optional[List[Any]] = None
    average_weather_temp: Optional[float] = None
    min_weather_temp: Optional[float] = None
    max_weather_temp: Optional[float] = None
    average_feels_like: Optional[float] = None
    min_feels_like: Optional[float] = None
    max_feels_like: Optional[float] = None
    average_wind_speed: Optional[float] = None
    average_wind_gust: Optional[float] = None
    prevailing_wind_deg: Optional[float] = None
    headwind_percent: Optional[float] = None
    tailwind_percent: Optional[float] = None
    average_clouds: Optional[float] = None
    max_rain: Optional[float] = None
    max_snow: Optional[float] = None
    carbs_ingested: Optional[float] = None
    pace: Optional[float] = None
    athlete_max_hr: Optional[int] = None
    group: Optional[str] = None
    icu_intensity: Optional[float] = None
    icu_efficiency_factor: Optional[float] = None
    icu_power_hr: Optional[float] = None
    session_rpe: Optional[float] = None
    average_stride: Optional[float] = None
    icu_average_watts: Optional[float] = None
    icu_variability_index: Optional[float] = None
    icu_power_spike_threshold: Optional[float] = None
    activity_link: Optional[str] = None
    activity_link_markdown: Optional[str] = None

    @classmethod
    def from_dict(cls, data: dict) -> 'IntervalsActivity':
        """
        Create an IntervalsActivity instance from a dictionary
        
        Args:
            data: Dictionary containing activity data from Intervals.icu API
            
        Returns:
            IntervalsActivity: A new instance of IntervalsActivity
        """
        valid_fields = {k: v for k, v in data.items() 
                       if k in cls.__dataclass_fields__ and not isinstance(v, dict)}
        # add the activity_link_markdown field by taking the id
        valid_fields['activity_link'] = f"https://intervals.icu/activities/{valid_fields['id']}"
        valid_fields['activity_link_markdown'] = f"[{valid_fields['name']}](https://intervals.icu/activities/{valid_fields['id']})"
        return cls(**valid_fields)
    
    def to_dict(self) -> dict:
        """
        Convert the IntervalsActivity instance to a dictionary
        
        Returns:
            dict: Dictionary representation of the activity
        """
        return {k: v for k, v in self.__dict__.items()}

    def to_json(self) -> str:
        """
        Convert the IntervalsActivity instance to a JSON string
        
        Returns:
            str: JSON representation of the activity
        """
        return json.dumps(self.to_dict())

    @classmethod
    def has_field(cls, field_name: str) -> bool:
        return any(field.name == field_name for field in fields(cls))