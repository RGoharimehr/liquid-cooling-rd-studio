using System.Text.Json;
using System.Text.Json.Serialization;

namespace LiquidCooling.Revit;

public sealed class Handoff
{
    [JsonPropertyName("schema_version")] public string SchemaVersion { get; set; } = "";
    [JsonPropertyName("config_hash")] public string ConfigHash { get; set; } = "";
    [JsonPropertyName("target")] public ImportTarget Target { get; set; } = new();
    [JsonPropertyName("components")] public List<Component> Components { get; set; } = [];
    [JsonPropertyName("connections")] public List<Joint> Connections { get; set; } = [];
    [JsonPropertyName("fluid_paths")] public List<FluidPath> FluidPaths { get; set; } = [];
    [JsonPropertyName("thermal_couplings")] public JsonElement Couplings { get; set; }
    [JsonPropertyName("preflight")] public PackagePreflight Preflight { get; set; } = new();

    public static Handoff Read(string path) => JsonSerializer.Deserialize<Handoff>(File.ReadAllText(path))
        ?? throw new InvalidDataException("The handoff package is empty.");

    public List<string> Validate()
    {
        List<string> errors = [];
        if (SchemaVersion != "2.0") errors.Add("Only handoff schema 2.0 is supported.");
        if (Target.Revit != "2027") errors.Add("This add-in requires a package targeting Revit 2027. Regenerate the package in the current studio.");
        if (ConfigHash.Length != 64 || ConfigHash.Any(c => !Uri.IsHexDigit(c))) errors.Add("A SHA-256 applied-configuration hash is required.");
        if (Preflight.GeometryBlockingFindings > 0) errors.Add($"The generator reports {Preflight.GeometryBlockingFindings} blocking geometry findings. Repair them before native import.");
        if (Components.Count == 0) errors.Add("The package contains no components.");
        if (Components.Select(c => c.Id).Distinct().Count() != Components.Count) errors.Add("Component IDs are duplicated.");
        Dictionary<string, (Component Owner, Port Port)> ports = [];
        foreach (Component c in Components)
        {
            if (string.IsNullOrWhiteSpace(c.Id) || string.IsNullOrWhiteSpace(c.Kind)) errors.Add("Each component requires an ID and kind.");
            if (!AllowedKinds.Contains(c.Kind)) errors.Add($"{c.Id}: unsupported kind '{c.Kind}'; supply a supported native mapping.");
            if (c.Kind == "pipe" && c.Ports.Count != 2) errors.Add($"{c.Id}: a pipe requires two oriented ports.");
            if (c.IsRoutingFitting && c.Ports.Count != (c.Kind == "tee" ? 3 : 2)) errors.Add($"{c.Id}: invalid fitting port count.");
            if (c.Center is not null && !VectorValid(c.Center)) errors.Add($"{c.Id}: invalid equipment center.");
            if (c.Size is not null && (!VectorValid(c.Size) || c.Size.Any(x => x <= 0))) errors.Add($"{c.Id}: invalid equipment envelope.");
            foreach (Port p in c.Ports)
            {
                if (!ports.TryAdd(p.Id, (c, p))) errors.Add($"Duplicate port identity {p.Id}.");
                if (!VectorValid(p.Xyz) || !VectorValid(p.Outward) || Math.Abs(Length(p.Outward) - 1) > 1e-5) errors.Add($"{p.Id}: finite position and unit outward direction are required.");
                if (p.NominalIn is not > 0 || p.OutsideM is not > 0 || p.InsideM is not > 0 || p.InsideM >= p.OutsideM) errors.Add($"{p.Id}: positive nominal size and 0 < ID < OD are required.");
                if (string.IsNullOrWhiteSpace(p.Circuit) || string.IsNullOrWhiteSpace(p.Service) || string.IsNullOrWhiteSpace(p.Node)) errors.Add($"{p.Id}: circuit, service, and node are required.");
            }
            if (c.Kind == "pipe" && c.Ports.Count == 2 && c.Ports.All(p => VectorValid(p.Xyz)))
            {
                double length = Distance(c.Ports[0].Xyz, c.Ports[1].Xyz);
                if (length < 0.00254) errors.Add($"{c.Id}: length is below Revit's 1/10 inch MEPCurve minimum.");
                if (c.Ports[0].Circuit != c.Ports[1].Circuit) errors.Add($"{c.Id}: a pipe cannot cross circuits.");
            }
        }
        HashSet<string> scheduled = [];
        foreach (Joint j in Connections)
        {
            if (j.Ports.Count is < 1 or > 2) errors.Add($"{j.Node}: explicit tees are required; a connection must have one boundary port or two component ports.");
            foreach (string id in j.Ports)
            {
                if (!scheduled.Add(id)) errors.Add($"{id}: port appears more than once in the connection schedule.");
                if (!ports.TryGetValue(id, out var found)) errors.Add($"{j.Node}: unknown port {id}.");
                else if (found.Port.Node != j.Node) errors.Add($"{id}: connection node disagrees with port node.");
            }
            if (j.Ports.Count != 2 || j.Ports.Any(id => !ports.ContainsKey(id))) continue;
            var a = ports[j.Ports[0]]; var b = ports[j.Ports[1]];
            if (a.Owner.Id == b.Owner.Id) errors.Add($"{j.Node}: external joint joins a component to itself.");
            if (a.Port.Circuit != b.Port.Circuit || a.Port.Service != b.Port.Service) errors.Add($"{j.Node}: cross-circuit fluid connection is forbidden.");
            if (VectorValid(a.Port.Xyz) && VectorValid(b.Port.Xyz) && Distance(a.Port.Xyz, b.Port.Xyz) > 1e-6) errors.Add($"{j.Node}: port coordinates do not coincide.");
            if (VectorValid(a.Port.Outward) && VectorValid(b.Port.Outward) && Dot(a.Port.Outward, b.Port.Outward) > -0.99999) errors.Add($"{j.Node}: port directions are not opposed; add the missing fitting.");
            if (Math.Abs((a.Port.NominalIn ?? 0) - (b.Port.NominalIn ?? 0)) > 1e-6) errors.Add($"{j.Node}: nominal sizes differ without a transition.");
        }
        foreach (string id in ports.Keys.Where(id => !scheduled.Contains(id))) errors.Add($"{id}: port is absent from connection schedule.");
        foreach (FluidPath path in FluidPaths)
        {
            Component? owner = Components.FirstOrDefault(c => c.Id == path.ComponentId);
            Port? a = owner?.Ports.FirstOrDefault(p => p.Node == path.From);
            Port? b = owner?.Ports.FirstOrDefault(p => p.Node == path.To);
            if (a is null || b is null) errors.Add($"{path.Id}: internal fluid path references unknown component ports.");
            else if (a.Circuit != b.Circuit || a.Service != b.Service) errors.Add($"{path.Id}: internal fluid path mixes separate circuits.");
        }
        return errors.Distinct().ToList();
    }

    public static readonly HashSet<string> AllowedKinds = ["pipe", "elbow", "tee", "reducer", "flex_connector", "quick_disconnect", "isolation_valve", "balancing_valve", "check_valve", "strainer", "air_separator", "expansion_tank", "pump", "cdu", "cdu_primary", "cdu_secondary", "cdu_enclosure", "chiller", "cooling_tower", "air_unit", "control_valve", "compute_rack", "network_rack", "rack_load", "rack_manifold", "vent", "drain", "boundary", "temperature_sensor", "pressure_sensor", "flow_meter"];
    public static bool VectorValid(double[] v) => v.Length == 3 && v.All(double.IsFinite);
    public static double Dot(double[] a, double[] b) => a.Zip(b).Sum(x => x.First * x.Second);
    public static double Length(double[] a) => Math.Sqrt(Dot(a, a));
    public static double Distance(double[] a, double[] b) => Length(a.Zip(b).Select(x => x.First - x.Second).ToArray());
}

public sealed class Component
{
    [JsonPropertyName("id")] public string Id { get; set; } = "";
    [JsonPropertyName("tag")] public string Tag { get; set; } = "";
    [JsonPropertyName("kind")] public string Kind { get; set; } = "";
    [JsonPropertyName("service")] public string Service { get; set; } = "";
    [JsonPropertyName("port_details")] public List<Port> Ports { get; set; } = [];
    [JsonPropertyName("center_m")] public double[]? Center { get; set; }
    [JsonPropertyName("size_m")] public double[]? Size { get; set; }
    [JsonPropertyName("rotation_deg")] public double RotationDegrees { get; set; }
    [JsonExtensionData] public Dictionary<string, JsonElement> Extra { get; set; } = [];
    [JsonIgnore] public bool IsRoutingFitting => Kind is "elbow" or "tee" or "reducer";
    [JsonIgnore] public double[] Origin => Center ?? (Ports.Count > 0 ? Enumerable.Range(0, 3).Select(i => Ports.Average(p => p.Xyz[i])).ToArray() : [0, 0, 0]);
}
public sealed class Port
{
    [JsonPropertyName("id")] public string Id { get; set; } = "";
    [JsonPropertyName("node_id")] public string Node { get; set; } = "";
    [JsonPropertyName("xyz_m")] public double[] Xyz { get; set; } = [];
    [JsonPropertyName("outward")] public double[] Outward { get; set; } = [];
    [JsonPropertyName("nominal_size_in")] public double? NominalIn { get; set; }
    [JsonPropertyName("od_m")] public double? OutsideM { get; set; }
    [JsonPropertyName("id_m")] public double? InsideM { get; set; }
    [JsonPropertyName("service")] public string Service { get; set; } = "";
    [JsonPropertyName("circuit_id")] public string Circuit { get; set; } = "";
}
public sealed class Joint
{
    [JsonPropertyName("node_id")] public string Node { get; set; } = "";
    [JsonPropertyName("ports")] public List<string> Ports { get; set; } = [];
}
public sealed class FluidPath
{
    [JsonPropertyName("id")] public string Id { get; set; } = "";
    [JsonPropertyName("component_id")] public string ComponentId { get; set; } = "";
    [JsonPropertyName("from_node")] public string From { get; set; } = "";
    [JsonPropertyName("to_node")] public string To { get; set; } = "";
}
public sealed class PackagePreflight
{
    [JsonPropertyName("geometry_blocking_findings")] public int GeometryBlockingFindings { get; set; }
}
public sealed class ImportTarget
{
    [JsonPropertyName("revit")] public string Revit { get; set; } = "";
}
public sealed class ImportSettings
{
    public string PipeTypeName { get; set; } = "";
    public Dictionary<string,string> PipeTypesByMaterial { get; set; } = [];
    public string LevelName { get; set; } = "";
    public string MechanicalEquipmentTemplate { get; set; } = "";
    public double PositionToleranceM { get; set; } = 0.001;
    public double BoreToleranceM { get; set; } = 0.0001;
}
