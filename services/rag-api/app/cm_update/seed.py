"""Explicit local fixtures only. Does NOT import or change real CourseMate production data."""
from pathlib import Path
from .db import Database,now,uid
from .config import Settings
from .auth import ensure_user
from .filesystem import parse_document,file_hash

def seed(cfg:Settings, documents:Path|None=None):
    """Create the standalone local fixture.

    `documents` points at a directory of sample PDFs. It is only used by the
    standalone reference store; integrated deployments never reach here because
    seed() refuses production and integrated modes outright.
    """
    if cfg.environment=='production' or cfg.integration_mode=='integrated': raise RuntimeError('Cannot seed production/integrated mode')
    db=Database(cfg.data_dir/'ui.sqlite3');db.initialize();(cfg.data_dir/'uploads').mkdir(exist_ok=True)
    for who,name in [('alice','秋同学'),('bob','林同学'),('admin','课程管理员')]:
        u=ensure_user(db,'local-'+who);db.execute('UPDATE cmui_users SET name=?,discoverable=1 WHERE id=?',(name,u['id']))
    for cid,name,color in [('cs3481','Fundamentals of Data Science','#38585b'),('ge2324','Art and Science of Data','#756480')]:
        db.execute('INSERT OR IGNORE INTO cmui_courses(id,code,name,color,visibility,official,created_at) VALUES (?,?,?,?,?,?,?)',(cid,cid.upper(),name,color,'public',1,now()))
    roots=[p for p in [documents,Path(__file__).resolve().parents[2]/'sample-documents'] if p is not None and p.is_dir()]
    for root in roots:
      for path in sorted(root.glob('*.pdf')):
        cid='cs3481' if 'Clustering' in path.name else 'ge2324'
        fid='sample_'+path.stem.lower()
        if db.one('SELECT id FROM cmui_files WHERE id=?',(fid,)): continue
        content=path.read_bytes();mime,parts,error=parse_document(path.name,content)
        folder='Tutorial' if 'Tutorial' in path.name else 'Lecture Slides'
        storage=fid+'.pdf';(cfg.data_dir/'uploads'/storage).write_bytes(content)
        with db.connect(True) as c:
            c.execute('INSERT INTO cmui_files VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',(fid,cid,None,path.name,folder,len(content),mime,storage,file_hash(content),'public','indexed',error,now()))
            for n,(page,text) in enumerate(parts): c.execute('INSERT INTO cmui_chunks VALUES (?,?,?,?,?)',(uid('chunk_'),fid,page,n,text))
    nodes=[('data','cs3481',None,'数据科学基础',0),('kdd','cs3481','data','KDD 数据科学流程',1),('cluster','cs3481',None,'聚类分析',2),('kmeans','cs3481','cluster','K-means 聚类',3),('dbscan','cs3481','cluster','DBSCAN 密度聚类',4),('core','cs3481','dbscan','核心点与邻域',5),('noise','cs3481','dbscan','边界点与噪声',6),('viz','ge2324',None,'数据与可视化',0),('reading','ge2324','viz','读懂数据图表',1),('story','ge2324','viz','用数据讲故事',2)]
    with db.connect(True) as c:
        for node in nodes: c.execute('INSERT OR IGNORE INTO cmui_nodes VALUES (?,?,?,?,?)',node)
    print('Local fixture seed complete. Official labels/PDFs are sample data, not production curriculum.')

if __name__=='__main__': seed(Settings())
