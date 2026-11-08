from typing import Literal
from fastapi import APIRouter,Depends,Query,Response
from .feed_api import repository_for
from .repository import Repository

router=APIRouter(prefix='/api/instagram',tags=['instagram'])


@router.get('/candidates')
def candidates(response:Response,status:Literal['pending','held','rejected','approved','active','existing','limited']|None=None,
               offset:int=Query(0,ge=0),limit:int=Query(30,ge=1,le=100),repository:Repository=Depends(repository_for)):
    response.headers['Cache-Control']='no-store'
    where=' WHERE status=?' if status else '';values=(status,) if status else ()
    with repository.database.connection() as conn:
        total=conn.execute('SELECT count(*) FROM instagram_candidates'+where,values).fetchone()[0]
        rows=conn.execute('SELECT username,url,discovered_from,status,reason,source_id,first_seen_at,last_seen_at,checked_at FROM instagram_candidates'+where+' ORDER BY last_seen_at DESC LIMIT ? OFFSET ?',(*values,limit,offset))
        return {'items':[dict(row) for row in rows],'total':total,'offset':offset,'limit':limit}
