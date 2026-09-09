"""OBJ meshes use the exact same component geometry as IFC4 and the web viewer."""
from pathlib import Path
from ifc4 import component_mesh
COLORS={'TCS':(.06,.55,.53),'FWS':(.80,.48,.15),'compute_rack':(.16,.24,.30),'network_rack':(.51,.41,.68),'cdu_enclosure':(.35,.56,.61),'attachment':(.60,.65,.62)}

def emit_mesh(graph,outdir):
    outdir=Path(outdir);lines=['# metres; Z up; conceptual envelopes','mtllib network.mtl'];offset=0;count=0
    for comp in graph['components']:
        mesh=comp.get('mesh') or component_mesh(graph,comp)
        if not mesh['vertices']:continue
        mat=comp['kind'] if comp['kind'] in COLORS else ('attachment' if comp.get('attachment') else comp.get('service','TCS'))
        if mat not in COLORS:mat='attachment'
        lines+=['o '+comp['id'],'usemtl '+mat]
        lines+=['v '+' '.join(f'{v:.7f}' for v in vertex) for vertex in mesh['vertices']]
        lines+=['f '+' '.join(str(i+offset+1) for i in face) for face in mesh['faces']]
        offset+=len(mesh['vertices']);count+=1
    (outdir/'network.obj').write_text('\n'.join(lines)+'\n')
    (outdir/'network.mtl').write_text('\n'.join('newmtl '+key+'\nKd '+' '.join(map(str,rgb))+'\nd 1.0\n' for key,rgb in COLORS.items()))
    return {'mesh_obj':'network.obj','mesh_mtl':'network.mtl','mesh_vertices':offset,'mesh_component_count':count,'mesh_status':'Shared IFC/OBJ/browser conceptual mesh; vendor fabrication geometry is not supplied.'}
