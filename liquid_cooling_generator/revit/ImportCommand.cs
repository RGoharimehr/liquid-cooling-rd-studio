using Autodesk.Revit.Attributes;
using Autodesk.Revit.DB;
using Autodesk.Revit.DB.Plumbing;
using Autodesk.Revit.DB.Structure;
using Autodesk.Revit.DB.ExtensibleStorage;
using Autodesk.Revit.UI;
using Microsoft.Win32;
using System.Text.Json;
using System.Security.Cryptography;
using System.Text;

namespace LiquidCooling.Revit;

[Transaction(TransactionMode.Manual)]
public class ImportCommand : IExternalCommand
{
    public Result Execute(ExternalCommandData data, ref string message, ElementSet elements)
    {
        var dialog = new OpenFileDialog { Filter = "RD Studio handoff|revit_handoff.json|JSON|*.json" };
        if (dialog.ShowDialog() != true) return Result.Cancelled;
        string path = dialog.FileName;
        string reportPath = Path.Combine(Path.GetDirectoryName(path)!, "revit_import_result.json");
        var report = new ImportReport();
        try
        {
            var doc = data.Application.ActiveUIDocument?.Document ?? throw new InvalidOperationException("Open a Revit MEP project before importing the handoff.");
            if (doc.IsFamilyDocument) throw new InvalidOperationException("Open a Revit project, not a family document.");
            if (data.Application.Application.VersionNumber != "2027") throw new InvalidOperationException("This add-in targets Revit 2027.");
            var package = Handoff.Read(path);
            report.ConfigHash = package.ConfigHash;
            report.RevitVersion = data.Application.Application.VersionNumber;
            report.RevitBuild = data.Application.Application.VersionBuild;
            report.Errors.AddRange(package.Validate());
            string settingsPath = Path.Combine(Path.GetDirectoryName(path)!, "revit", "import-settings.json");
            if (!File.Exists(settingsPath)) throw new FileNotFoundException("Extract the complete package, then configure revit/import-settings.json.", settingsPath);
            var settings = JsonSerializer.Deserialize<ImportSettings>(File.ReadAllText(settingsPath))!;
            var allPipeTypes = new FilteredElementCollector(doc).OfClass(typeof(PipeType)).Cast<PipeType>().ToArray();
            var pipeTypes = new Dictionary<string,PipeType>();
            foreach (var component in package.Components.Where(c => c.Kind == "pipe"))
            {
                string material = component.Extra.TryGetValue("material",out var value) ? value.GetString() ?? "" : "";
                string typeName = settings.PipeTypesByMaterial.GetValueOrDefault(material,settings.PipeTypeName);
                var type = allPipeTypes.FirstOrDefault(t => t.Name == typeName);
                if (type == null) { string error = "Required native PipeType not found for " + material + ": " + typeName; if (!report.Errors.Contains(error)) report.Errors.Add(error); }
                else pipeTypes[component.Id] = type;
            }
            var level = new FilteredElementCollector(doc).OfClass(typeof(Level)).Cast<Level>().FirstOrDefault(x => x.Name == settings.LevelName);
            if (level == null) report.Errors.Add("Required project level not found: " + settings.LevelName);
            if (!File.Exists(settings.MechanicalEquipmentTemplate)) report.Errors.Add("Set MechanicalEquipmentTemplate to the installed, unhosted Metric Mechanical Equipment.rft template.");
            if (!(settings.PositionToleranceM > 0 && settings.PositionToleranceM <= .005 && settings.BoreToleranceM > 0 && settings.BoreToleranceM <= .001)) report.Errors.Add("Import tolerances are outside supported limits.");
            if (report.Errors.Count > 0) throw new InvalidDataException("Preflight failed. See revit_import_result.json.");
            using var group = new TransactionGroup(doc, "Import RD Studio " + package.ConfigHash[..12]);
            group.Start();
            try
            {
                var generated = new Dictionary<string, FamilySymbol>();
                var symbols = new Dictionary<string, FamilySymbol>();
                // Family generation is outside an active project transaction. The group
                // rolls back loaded families as well as all model instances on failure.
                foreach (var c in package.Components.Where(c => c.Kind != "pipe"))
                {
                    string key = ReferenceFamily.Key(c);
                    if (!generated.TryGetValue(key, out var symbol))
                    {
                        symbol = ReferenceFamily.Create(data.Application.Application, doc, settings.MechanicalEquipmentTemplate, c, key);
                        generated.Add(key, symbol);
                    }
                    symbols[c.Id] = symbol;
                }
                using var tx = new Transaction(doc, "Create native connected MEP network");
                tx.Start();
                var systems = new Dictionary<string, PipingSystemType>();
                foreach (string circuit in package.Components.SelectMany(c => c.Ports).Select(p => p.Circuit).Distinct())
                {
                    string name = "RD " + circuit + " " + package.ConfigHash[..8];
                    systems[circuit] = new FilteredElementCollector(doc).OfClass(typeof(PipingSystemType)).Cast<PipingSystemType>().FirstOrDefault(s => s.Name == name)
                        ?? PipingSystemType.Create(doc, MEPSystemClassification.SupplyHydronic, name);
                }
                var imported = new Dictionary<string, Element>();
                foreach (var c in package.Components)
                {
                    Element element;
                    if (c.Kind == "pipe")
                    {
                        var a = c.Ports[0]; var b = c.Ports[1];
                        var pipe = Pipe.Create(doc, systems[a.Circuit].Id, pipeTypes[c.Id].Id, level!.Id, Feet(a.Xyz), Feet(b.Xyz));
                        pipe.get_Parameter(BuiltInParameter.RBS_PIPE_DIAMETER_PARAM).Set(a.NominalIn!.Value / 12);
                        element = pipe;
                    }
                    else
                    {
                        var symbol = symbols[c.Id];
                        if (!symbol.IsActive) symbol.Activate();
                        doc.Regenerate();
                        element = doc.Create.NewFamilyInstance(Feet(c.Origin), symbol, level!, StructuralType.NonStructural);
                    }
                    Store(element, package.ConfigHash, c);
                    imported[c.Id] = element;
                    report.Elements.Add(new { component_id = c.Id, element_id = element.Id.Value, unique_id = element.UniqueId, category = element.Category?.Name });
                }
                doc.Regenerate();
                var portMap = new Dictionary<string, Connector>();
                foreach (var c in package.Components)
                {
                    Connector[] actual = Connectors(imported[c.Id]);
                    if (actual.Length != c.Ports.Count) throw new InvalidDataException($"{c.Id}: expected {c.Ports.Count} ports, created {actual.Length}.");
                    var consumed = new HashSet<int>();
                    foreach (var p in c.Ports)
                    {
                        var connector = actual.Where(x => !consumed.Contains(x.Id)).OrderBy(x => x.Origin.DistanceTo(Feet(p.Xyz))).First();
                        if (connector.Origin.DistanceTo(Feet(p.Xyz)) > ToFeet(settings.PositionToleranceM)) throw new InvalidDataException($"{p.Id}: target connector coordinate differs from package.");
                        if (connector.CoordinateSystem.BasisZ.Normalize().DotProduct(new XYZ(p.Outward[0], p.Outward[1], p.Outward[2])) < .9999) throw new InvalidDataException($"{p.Id}: target connector direction differs from package.");
                        if (Math.Abs(connector.Radius * 2 - p.NominalIn!.Value / 12) > ToFeet(settings.BoreToleranceM)) throw new InvalidDataException($"{p.Id}: target connector nominal size differs from package.");
                        consumed.Add(connector.Id); portMap[p.Id] = connector;
                    }
                    if (imported[c.Id] is Pipe nativePipe)
                    {
                        double id = nativePipe.get_Parameter(BuiltInParameter.RBS_PIPE_INNER_DIAM_PARAM).AsDouble();
                        double od = nativePipe.get_Parameter(BuiltInParameter.RBS_PIPE_OUTER_DIAMETER).AsDouble();
                        if (Math.Abs(id-ToFeet(c.Ports[0].InsideM!.Value)) > ToFeet(settings.BoreToleranceM) || Math.Abs(od-ToFeet(c.Ports[0].OutsideM!.Value)) > ToFeet(settings.BoreToleranceM))
                            throw new InvalidDataException($"{c.Id}: PipeType segment schedule does not match package ID/OD. Configure the pipe segment sizes/material, then retry.");
                    }
                }
                foreach (var joint in package.Connections.Where(j => j.Ports.Count == 2))
                {
                    var a = portMap[joint.Ports[0]]; var b = portMap[joint.Ports[1]];
                    if (!a.IsConnectedTo(b)) a.ConnectTo(b);
                }
                doc.Regenerate();
                foreach (var joint in package.Connections.Where(j => j.Ports.Count == 2))
                    if (!portMap[joint.Ports[0]].IsConnectedTo(portMap[joint.Ports[1]])) throw new InvalidDataException(joint.Node + ": Revit did not retain the connection.");
                // Check final positions again: ConnectTo may attempt to insert or move fittings.
                foreach (var p in package.Components.SelectMany(c => c.Ports))
                    if (portMap[p.Id].Origin.DistanceTo(Feet(p.Xyz)) > ToFeet(settings.PositionToleranceM)) throw new InvalidDataException(p.Id + ": Revit changed the route while connecting.");
                if (tx.Commit() != TransactionStatus.Committed) throw new InvalidOperationException("Revit did not commit the native network transaction.");
                if (group.Assimilate() != TransactionStatus.Committed) throw new InvalidOperationException("Revit did not commit the native import transaction group.");
                report.Status = "NATIVE_REVIT_IMPORT_CONNECTED";
                report.CheckedConnections = package.Connections.Count(j => j.Ports.Count == 2);
            }
            catch { if (group.GetStatus() == TransactionStatus.Started) group.RollBack(); throw; }
            File.WriteAllText(reportPath, JsonSerializer.Serialize(report, JsonOptions));
            TaskDialog.Show("RD Studio", $"Imported {report.Elements.Count} native elements and verified {report.CheckedConnections} external joints.\n\nSave the Revit 2027 RVT. Before transfer, confirm your installed Flownex Network Builder explicitly supports Revit 2027. Flownex 2025 R3 documents Revit 2026 support; 2027 transfer is not verified. Complete the target component mappings; this add-in has not performed a Flownex transfer.\n\nReport: {reportPath}");
            return Result.Succeeded;
        }
        catch (Exception e)
        {
            report.Status = "FAILED_NO_MODEL_COMMITTED"; report.Errors.Add(e.Message);
            File.WriteAllText(reportPath, JsonSerializer.Serialize(report, JsonOptions));
            message = e.Message + "\nReport: " + reportPath;
            return Result.Failed;
        }
    }
    internal static readonly JsonSerializerOptions JsonOptions = new() { WriteIndented = true };
    internal static double ToFeet(double m) => m / .3048;
    internal static XYZ Feet(double[] m) => new(ToFeet(m[0]), ToFeet(m[1]), ToFeet(m[2]));
    internal static Connector[] Connectors(Element e) => (e is MEPCurve curve ? curve.ConnectorManager.Connectors : e is FamilyInstance f && f.MEPModel != null ? f.MEPModel.ConnectorManager.Connectors : new ConnectorSet()).Cast<Connector>().Where(c => c.Domain == Domain.DomainPiping).ToArray();
    static void Store(Element element, string hash, Component c)
    {
        var id = new Guid("07f88237-5570-4a16-8f96-dd4307294d63");
        var schema = Schema.Lookup(id);
        if (schema == null)
        {
            var builder = new SchemaBuilder(id); builder.SetSchemaName("RDStudioContractV2");
            builder.AddSimpleField("ComponentId", typeof(string)); builder.AddSimpleField("ConfigurationHash", typeof(string)); builder.AddSimpleField("ComponentJson", typeof(string));
            schema = builder.Finish();
        }
        var entity = new Entity(schema); entity.Set("ComponentId", c.Id); entity.Set("ConfigurationHash", hash); entity.Set("ComponentJson", JsonSerializer.Serialize(c)); element.SetEntity(entity);
        element.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)?.Set(c.Id);
        element.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)?.Set("RD Studio " + hash[..12] + " / " + c.Kind + " / reference geometry; vendor mapping required");
    }
}
public sealed class ImportReport
{
    public string Status { get; set; } = "PREFLIGHT";
    public string ConfigHash { get; set; } = "";
    public string RevitVersion { get; set; } = "";
    public string RevitBuild { get; set; } = "";
    public List<string> Errors { get; set; } = [];
    public List<object> Elements { get; set; } = [];
    public int CheckedConnections { get; set; }
    public string FlownexStatus { get; set; } = "NOT_TRANSFERRED_OR_TESTED";
    public string FlownexRevit2027Compatibility { get; set; } = "NOT_CONFIRMED_BY_VENDOR_SOURCE";
    public string FamilyStatus { get; set; } = "Procedural reference envelopes, native MEP connectors; vendor qualification and target-library mapping required";
}
