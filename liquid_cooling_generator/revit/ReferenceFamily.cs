using Autodesk.Revit.ApplicationServices;
using Autodesk.Revit.DB;
using Autodesk.Revit.DB.Plumbing;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;

namespace LiquidCooling.Revit;

// Unhosted, editable native families with connector faces built in family space.
// These are project reference envelopes, not manufacturer-qualified families.
internal static class ReferenceFamily
{
    public static string Key(Component c)
    {
        var payload = new { c.Kind, c.Size, c.RotationDegrees, Ports = c.Ports.Select(p => new { X = p.Xyz.Zip(c.Origin).Select(x => Math.Round(x.First-x.Second,6)), p.Outward, p.NominalIn, p.Service, p.Circuit }) };
        return Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(JsonSerializer.Serialize(payload))))[..20];
    }
    public static FamilySymbol Create(Application app, Document project, string template, Component c, string key)
    {
        string name = "RD_" + c.Kind + "_" + key;
        var existing = new FilteredElementCollector(project).OfClass(typeof(FamilySymbol)).Cast<FamilySymbol>().FirstOrDefault(s => s.Family.Name == name);
        if (existing != null) return existing;
        Document family = app.NewFamilyDocument(template);
        string folder = Path.Combine(Path.GetTempPath(), "RDStudio", Guid.NewGuid().ToString("N")); Directory.CreateDirectory(folder);
        try
        {
            using (var tx = new Transaction(family, "Create reference envelope and oriented ports"))
            {
                tx.Start();
                var category = c.IsRoutingFitting ? BuiltInCategory.OST_PipeFitting : c.Size != null ? BuiltInCategory.OST_MechanicalEquipment : BuiltInCategory.OST_PipeAccessory;
                family.OwnerFamily.FamilyCategory = Category.GetCategory(family, category);
                var partType = family.OwnerFamily.get_Parameter(BuiltInParameter.FAMILY_CONTENT_PART_TYPE);
                if (partType != null && !partType.IsReadOnly && c.Size == null)
                    partType.Set((int)(c.Kind == "elbow" ? PartType.Elbow : c.Kind == "tee" ? PartType.Tee : c.Kind == "reducer" ? PartType.Transition : PartType.BreaksInto));
                if (family.FamilyManager.CurrentType == null) family.FamilyManager.NewType("Reference");
                var origin = ImportCommand.Feet(c.Origin);
                if (c.Size != null)
                {
                    var size = ImportCommand.Feet(c.Size); double angle = c.RotationDegrees*Math.PI/180;
                    var x = new XYZ(Math.Cos(angle),Math.Sin(angle),0); var y = new XYZ(-Math.Sin(angle),Math.Cos(angle),0);
                    Pad(family, new XYZ(0,0,-size.Z/2), XYZ.BasisZ, x, y, size.X/2, size.Y/2, size.Z);
                }
                else if (c.Ports.Count >= 2)
                {
                    var points = c.Ports.Select(p => ImportCommand.Feet(p.Xyz)-origin).ToArray();
                    double radius = ImportCommand.ToFeet(c.Ports.Max(p => p.OutsideM ?? .05))/2;
                    if (c.Kind == "elbow")
                    {
                        // center_m is the tangent intersection, not the circle center.
                        var circleCenter = points[0]+points[1];
                        var mid = circleCenter+(points[0]-circleCenter+points[1]-circleCenter)/Math.Sqrt(2);
                        var arc = Arc.Create(points[0],points[1],mid);
                        var path = new CurveLoop(); path.Append(arc);
                        var normal = arc.ComputeDerivatives(arc.GetEndParameter(0),false).BasisX.Normalize();
                        var profile = Circle(points[0],normal,radius);
                        FreeFormElement.Create(family,GeometryCreationUtilities.CreateSweptGeometry(path,0,arc.GetEndParameter(0),new List<CurveLoop>{profile}));
                    }
                    else if (c.Kind == "tee")
                    {
                        foreach (var end in points) Tube(family,XYZ.Zero,end,radius);
                    }
                    else Tube(family,points[0],points[1],radius);
                }
                var connectors = new List<(Port Port, ConnectorElement Connector)>();
                foreach (var p in c.Ports)
                {
                    var end = ImportCommand.Feet(p.Xyz) - origin;
                    var normal = new XYZ(p.Outward[0],p.Outward[1],p.Outward[2]).Normalize();
                    var x = normal.CrossProduct(Math.Abs(normal.Z)<.9 ? XYZ.BasisZ : XYZ.BasisX).Normalize();
                    var y = normal.CrossProduct(x).Normalize();
                    // The end face is at the exact contract coordinate; the pad grows inward.
                    double radius = p.NominalIn!.Value/24, depth = ImportCommand.ToFeet(.02);
                    var extrusion = Pad(family, end-normal*depth, normal, x, y, radius, radius, depth);
                    family.Regenerate();
                    var options = new Options { ComputeReferences=true };
                    PlanarFace? face = extrusion.get_Geometry(options).OfType<Solid>().SelectMany(s => s.Faces.Cast<Face>()).OfType<PlanarFace>()
                        .Where(f => f.FaceNormal.Normalize().DotProduct(normal)>.9999).OrderBy(f => f.Origin.DistanceTo(end)).FirstOrDefault();
                    if (face?.Reference == null) throw new InvalidOperationException(p.Id + ": unable to create a referenced connector face.");
                    var connector = ConnectorElement.CreatePipeConnector(family, c.Size != null ? PipeSystemType.SupplyHydronic : PipeSystemType.Fitting, face.Reference);
                    connector.get_Parameter(BuiltInParameter.CONNECTOR_RADIUS).Set(radius);
                    connectors.Add((p,connector));
                }
                // Only link the pair belonging to the same circuit in four-port equipment.
                // No fluid link is ever introduced between FWS/TCS or FWS/CWS.
                if (c.Size != null)
                    foreach (var circuit in connectors.GroupBy(x => x.Port.Circuit))
                    {
                        var pair = circuit.ToArray();
                        if (pair.Length == 2) pair[0].Connector.SetLinkedConnectorElement(pair[1].Connector);
                    }
                tx.Commit();
            }
            family.SaveAs(Path.Combine(folder,name+".rfa"),new SaveAsOptions { OverwriteExistingFile=true });
            var loaded = family.LoadFamily(project, new KeepExistingFamilies());
            return (FamilySymbol)project.GetElement(loaded.GetFamilySymbolIds().First());
        }
        finally { family.Close(false); try { Directory.Delete(folder,true); } catch (IOException) { } }
    }
    static Extrusion Pad(Document doc, XYZ start, XYZ normal, XYZ x, XYZ y, double halfX, double halfY, double depth)
    {
        var corners = new[] { start-x*halfX-y*halfY,start+x*halfX-y*halfY,start+x*halfX+y*halfY,start-x*halfX+y*halfY };
        var loop = new CurveArray(); for(int i=0;i<4;i++)loop.Append(Line.CreateBound(corners[i],corners[(i+1)%4]));
        var profile = new CurveArrArray(); profile.Append(loop);
        var plane = SketchPlane.Create(doc,Plane.CreateByNormalAndOrigin(normal,start));
        return doc.FamilyCreate.NewExtrusion(true,profile,plane,depth);
    }
    static CurveLoop Circle(XYZ center,XYZ normal,double radius)
    {
        var x=normal.CrossProduct(Math.Abs(normal.Z)<.9?XYZ.BasisZ:XYZ.BasisX).Normalize(); var y=normal.CrossProduct(x).Normalize();
        var loop=new CurveLoop(); loop.Append(Arc.Create(center,radius,0,Math.PI,x,y)); loop.Append(Arc.Create(center,radius,Math.PI,2*Math.PI,x,y)); return loop;
    }
    static void Tube(Document doc,XYZ start,XYZ end,double radius)
    {
        var delta=end-start;
        FreeFormElement.Create(doc,GeometryCreationUtilities.CreateExtrusionGeometry(new List<CurveLoop>{Circle(start,delta.Normalize(),radius)},delta.Normalize(),delta.GetLength()));
    }
    sealed class KeepExistingFamilies : IFamilyLoadOptions
    {
        public bool OnFamilyFound(bool familyInUse,out bool overwriteParameterValues) { overwriteParameterValues=false; return true; }
        public bool OnSharedFamilyFound(Family sharedFamily,bool familyInUse,out FamilySource source,out bool overwriteParameterValues) { source=FamilySource.Project;overwriteParameterValues=false;return true; }
    }
}
