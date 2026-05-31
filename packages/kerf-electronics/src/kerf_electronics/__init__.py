"""kerf-electronics: RF/SPICE/autoroute/pour plugin for Kerf."""
from kerf_electronics.voltage_drop import (  # noqa: F401
    ConductorSpec,
    CircuitSpec,
    VoltageDropReport,
    check_voltage_drop,
)
from kerf_electronics.wire_ampacity_derate import (  # noqa: F401
    WireSpec,
    InstallationConditions,
    DeratedAmpacityReport,
    compute_derated_ampacity,
)
from kerf_electronics.pcb_trace_current import (  # noqa: F401
    PcbTraceSpec,
    PcbTraceCurrentReport,
    compute_pcb_trace_max_current,
)
from kerf_electronics.diffpair_skew_check import (  # noqa: F401
    DiffPairSpec,
    DiffPairSkewReport,
    check_diffpair_skew,
)
from kerf_electronics.crystal_load_cap import (  # noqa: F401
    CrystalSpec,
    PCBLayoutSpec,
    CrystalLoadCapReport,
    compute_crystal_load_caps,
)
from kerf_electronics.emi_filter_design import (  # noqa: F401
    EmiFilterSpec,
    EmiFilterReport,
    design_emi_filter,
)
from kerf_electronics.dc_dc_ripple import (  # noqa: F401
    BuckConverterSpec,
    ConverterRippleReport,
    compute_buck_ripple,
)
from kerf_electronics.ldo_dropout_check import (  # noqa: F401
    LDOSpec,
    LDODropoutReport,
    check_ldo_dropout,
)
from kerf_electronics.fet_soa_check import (  # noqa: F401
    FETSpec,
    FETOperatingPoint,
    FETSOAReport,
    check_fet_soa,
)
from kerf_electronics.inductor_core_saturation import (  # noqa: F401
    InductorCoreSpec,
    InductorCurrentSpec,
    CoreSaturationReport,
    check_inductor_saturation,
)
from kerf_electronics.op_amp_offset_drift import (  # noqa: F401
    OpAmpSpec,
    CircuitSpec as OpAmpCircuitSpec,
    OpAmpOffsetReport,
    compute_op_amp_drift,
)
from kerf_electronics.zener_clamp_design import (  # noqa: F401
    ZenerClampSpec,
    ZenerClampReport,
    design_zener_clamp,
)
from kerf_electronics.fuse_i2t_check import (  # noqa: F401
    FuseSpec,
    FaultSpec,
    FuseI2tReport,
    check_fuse_i2t,
)
from kerf_electronics.pcb_via_current import (  # noqa: F401
    PcbViaSpec,
    PcbViaCurrentReport,
    compute_pcb_via_max_current,
)
from kerf_electronics.optocoupler_ctr import (  # noqa: F401
    OptocouplerSpec,
    CircuitSpec as OptocouplerCircuitSpec,
    OptocouplerReport,
    analyze_optocoupler,
)
from kerf_electronics.zener_tc_drift import (  # noqa: F401
    ZenerSpec,
    OperatingSpec as ZenerOperatingSpec,
    ZenerDriftReport,
    compute_zener_drift,
)
