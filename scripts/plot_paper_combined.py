"""Legible two-column-paper figure from the existing combined test only."""
import json
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'.local/paper-revision'


def main():
    r=json.loads((ROOT/'artifacts/operator-crowd-100-users/combined-results.json').read_text())
    rows=r['observations'];phases=list(dict.fromkeys(x['phase'] for x in rows));cohorts=list(dict.fromkeys(x['cohort'] for x in rows))
    plt.rcParams.update({'font.family':'DejaVu Sans','font.size':8,'axes.spines.top':False,'axes.spines.right':False,
        'pdf.fonttype':42,'ps.fonttype':42,'savefig.facecolor':'white'})
    fig,axs=plt.subplots(2,2,figsize=(7.16,6.15),layout='constrained')
    ax=axs[0,0]
    matrix=np.array([[int(next(x for x in rows if x['phase']==p and x['cohort']==c)['actual_source']=='crowd') for p in phases] for c in cohorts])
    ax.imshow(matrix,cmap=ListedColormap(['#eeeeee','#737373']),vmin=0,vmax=1,aspect='auto')
    for y,c in enumerate(cohorts):
        for x,p in enumerate(phases):
            item=next(v for v in rows if v['cohort']==c and v['phase']==p)
            code={'underground':'U','transition':'T','surface':'S'}[item['actual_context']]
            ax.text(x,y,('Crowd' if matrix[y,x] else 'Static')+'\n'+code,ha='center',va='center',fontsize=7,
                color='white' if matrix[y,x] else 'black')
    ax.set_xticks(range(5),['Initial','Boundary','After','Expiry','Recovery'],fontsize=7)
    ax.set_yticks(range(4),['DMRC U to S','DMRC S to U','NMRC out','NMRC in'],fontsize=7)
    ax.tick_params(length=0);ax.set_title('(a) Source and segment context',loc='left',fontweight='bold',fontsize=8)
    ax=axs[0,1];x=np.arange(5)
    subset=[next(v for v in rows if v['cohort']==cohorts[0] and v['phase']==p) for p in phases]
    ax.plot(x,[v['baseline_seconds']/60 for v in subset],color='black',marker='s',markersize=3,linestyle='--',label='Operator baseline')
    ax.plot(x,[v['actual_journey_seconds']/60 for v in subset],color='black',marker='o',markersize=3,label='Baseline + crowd')
    ax.set_xticks(x,['Initial','Boundary','After','Expiry','Recovery'],fontsize=7);ax.set_ylabel('Remaining duration (min)',fontsize=8)
    ax.set_title('(b) Scripted DMRC query sequence',loc='left',fontweight='bold',fontsize=8)
    ax.legend(fontsize=7,frameon=False,loc='upper left');ax.grid(axis='y',alpha=.22)
    ax=axs[1,0];labels=['Validated','Historical','Rejected'];values=[r['processing_outcomes'][v.lower()] for v in labels]
    bars=ax.bar(labels,values,color=['#666666','#bcbcbc','#eeeeee'],edgecolor='black',width=.6)
    for bar,value in zip(bars,values):ax.text(bar.get_x()+bar.get_width()/2,value+5,str(value),ha='center',fontsize=8)
    ax.set_ylim(0,240);ax.set_ylabel('Unique reports',fontsize=8);ax.set_title('(c) Recorded worker outcomes',loc='left',fontweight='bold',fontsize=8)
    ax.tick_params(axis='x',labelsize=8)
    ax=axs[1,1]
    for label,vals,style in [('HTTP (n = 400)',[v['elapsed_ms']/1000 for v in r['acks']],'-'),
        ('Crowd update (n = 250)',[v['observed_to_matching_ws_ms']/1000 for v in rows if v['observed_to_matching_ws_ms'] is not None],'--')]:
        vals=np.sort(vals);ax.step(vals,np.arange(1,len(vals)+1)/len(vals),where='post',color='black',linestyle=style,label=label)
    ax.set_ylim(0,1.04);ax.set_xlabel('Latency (s)',fontsize=8);ax.set_ylabel('Cumulative proportion',fontsize=8)
    ax.set_title('(d) Local delivery latency',loc='left',fontweight='bold',fontsize=8)
    ax.legend(fontsize=7,frameon=False,loc='lower right');ax.grid(alpha=.22)
    OUT.mkdir(parents=True,exist_ok=True)
    fig.savefig(OUT/'paper-figure-10.pdf')
    fig.savefig(OUT/'paper-figure-10.png',dpi=300)
    plt.close(fig);print('Paper-size Figure 10 generated from recorded measurements.')


if __name__=='__main__':main()
