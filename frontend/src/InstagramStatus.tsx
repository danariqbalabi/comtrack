import {useEffect,useState} from 'react'
import {api,dateTime,safeLink} from './api'

type Candidate={username:string;url:string;discovered_from:string;status:string;reason:string|null;checked_at:string|null;source_id:number|null}
type Results={items:Candidate[];total:number}
const labels:Record<string,string>={pending:'Menunggu pemeriksaan',held:'Perlu diperiksa',rejected:'Ditolak',approved:'Lolos klasifikasi',active:'Pantauan aktif',existing:'Sudah terdaftar',limited:'Batas tercapai'}
export default function InstagramStatus(){
  const [data,setData]=useState<Results|null>(null),[error,setError]=useState(''),[page,setPage]=useState(0)
  useEffect(()=>{
    let disposed=false
    async function load(){try{const result=await api<Results>(`/instagram/candidates?offset=${page*30}`);if(!disposed){setData(result);setError('')}}catch(err){if(!disposed)setError(err instanceof Error?err.message:'Status Instagram gagal dimuat.')}}
    void load();const timer=setInterval(()=>void load(),10000)
    return()=>{disposed=true;clearInterval(timer)}
  },[page])
  return <div className="panel"><h2>Akun Instagram</h2><p className="muted">Hanya profil yang terbukti publik dan bio-nya jelas sebagai media lomba atau penyelenggara. Akun pribadi ditolak, akun ambigu ditahan. Pemeriksaan profil dan postingan memerlukan provider serta jatah biaya harian bersama discovery.</p>
    {error&&<p role="alert" className="error-text">{error}</p>}
    {data?.items.map(item=><div className="source-row" key={item.username}><div><a href={safeLink(item.url)} target="_blank" rel="noreferrer">@{item.username}</a><p>{labels[item.status]||item.status}{item.source_id?` - sumber #${item.source_id}`:''}</p><p>{item.reason}</p><small>Ditemukan dari: <a href={safeLink(item.discovered_from)} target="_blank" rel="noreferrer">sumber penemuan</a> - Diperiksa {dateTime(item.checked_at)}</small></div></div>)}
    {data&&!data.total&&<p>Belum ada akun ditemukan. Discovery akan menyimpan URL profil dari hasil pencarian atau tautan website.</p>}
    {data&&data.total>30&&<div className="pagination"><button disabled={!page} onClick={()=>setPage(page-1)}>Sebelumnya</button><span>{page+1}/{Math.ceil(data.total/30)}</span><button disabled={(page+1)*30>=data.total} onClick={()=>setPage(page+1)}>Berikutnya</button></div>}
  </div>
}
