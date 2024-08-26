import numpy as np

from ochre.Models import StratifiedWaterModel
from ochre.utils import convert

# Water Constants
water_density = 1000  # kg/m^3
water_density_liters = 1  # kg/L
water_cp = 4.183  # kJ/kg-K
water_conductivity = 0.6406  # W/m-K
water_c = water_cp * water_density_liters * 1000  # heat capacity with useful units: J/K-L

# PCM properties from manufacturer, same units as water properties
solid = {
    "pcm_density": 904,
    "pcm_density_liters": 0.904,
    "pcm_cp": 1.9,
    "pcm_conductivity": 0.28,
    "pcm_c": 1717.6,
}
liquid = {
    "pcm_density": 829,
    "pcm_density_liters": 0.829,
    "pcm_cp": 2.2,
    "pcm_conductivity": 0.16,
    "pcm_c": 1823.8,
}
pcm_transition = 53  # C


class TankWithPCM(StratifiedWaterModel):
    """
    Water Tank Model with Phase Change Material

    Defaults to a 13 node tank with 12 water nodes and 1 PCM node.
    """
    name = 'Water Tank with PCM'

    def __init__(self, pcm_water_node=5, pcm_vol_fraction=0.5, **kwargs):
        super().__init__(**kwargs)

        # PCM node data
        self.pcm_water_node = pcm_water_node
        self.pcm_vol_fraction = pcm_vol_fraction
        self.t_pcm_idx = self.state_names.index("T_PCM")
        self.h_pcm_idx = self.input_names.index("H_PCM")
        
        self.pcm_heat_to_water = None  # in W

    def load_rc_data(self, **kwargs):
        # TODO:
        # - C list should have PCM node at the bottom

        rc_params = super().load_rc_data(self, **kwargs)

        # Add PCM capacitance, default to solid state for now
        pcm_node_vol_fraction = self.vol_fractions[self.pcm_water_node]
        pcm_volume = self.volume * pcm_node_vol_fraction * self.pcm_vol_fraction
        rc_params["C_PCM"] = solid["pcm_c"] * pcm_volume

        # Reduce water volume and vol_fractions from PCM volume
        self.volume -= pcm_volume
        self.vol_fractions[self.pcm_water_node] *= 1 - self.pcm_vol_fraction
        self.vol_fractions = self.vol_fractions / sum(self.vol_fractions)

        # Reduce water node capacitance
        rc_params[f"C_WH{self.pcm_water_node + 1}"] *= 1 - self.pcm_vol_fraction
        
        # Add water-PCM resistance, default to solid state for now
        rc_params[f"R_PCM_WH{self.pcm_water_node + 1}"] = pcm_volume / solid["pcm_conductivity"]

        return rc_params

    def get_pcm_heat_xfer(self):
        raise NotImplementedError()

    def update_inputs(self, schedule_inputs=None):
        # Note: self.inputs_init are not updated here, only self.current_schedule
        super().update_inputs(schedule_inputs)

        # get zone temperature from schedule
        t_zone = self.current_schedule['Zone Temperature (C)']

        # update heat injections from water draw
        # FUTURE: revise CW and DW when event based schedules are added
        heats_to_model = self.update_water_draw()

        # update heat injections from PCM
        self.pcm_heat_to_water = self.get_pcm_heat_xfer()
        heats_to_model[self.pcm_water_node] += self.pcm_heat_to_water
        heats_to_model[self.t_pcm_idx] -= self.pcm_heat_to_water

        # update water tank model
        self.inputs_init = np.concatenate(([t_zone], heats_to_model))

    def generate_results(self):
        # Note: most results are included in Dwelling/WH. Only inputs and states are saved to self.results
        results = super().generate_results()

        if self.verbosity >= 6:
            water_states = self.states[:self.n_nodes]
            results["Hot Water Average Temperature (C)"] = water_states.dot(self.vol_fractions)
            results["Hot Water Maximum Temperature (C)"] = water_states.max()
            results["Hot Water Minimum Temperature (C)"] = water_states.min()
            results['Water Tank PCM Temperature (C)'] = self.states[self.t_pcm_idx]
            results['Water Tank PCM Heat Injected (W)'] = self.h_injections
        return results
