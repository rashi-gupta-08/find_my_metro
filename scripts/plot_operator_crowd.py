"""Publication figure from the combined experiment's saved measurements only."""
import json
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'artifacts/operator-crowd-100-users'


def main():
    result=json.loads((OUT/'combined-results.json').read_text())
    assert json.loads((OUT/'verification.json').read_text())['all_checks_passed']
    rows=result['observations'];phases=list(dict.fromkeys(r['phase'] for r in rows));cohorts=list(dict.fromkeys(r['cohort'] for r in rows))
    plt.rcParams.update({'font.family':'DejaVu Sans','font.size':9,'axes.spines.top':False,'axes.spines.right':False,
        'pdf.fonttype':42,'ps.fonttype':42,'savefig.facecolor':'white'})
    fig,axs=plt.subplots(2,2,figsize=(11.4,7.8),layout='constrained')
    ax=axs[0,0]
    matrix=np.array([[int(next(r for r in rows if r['cohort']==c and r['phase']==p)['actual_source']=='crowd') for p in phases] for c in cohorts])
    ax.imshow(matrix,cmap=ListedColormap(['#eeeeee','#767676']),vmin=0,vmax=1,aspect='auto')
    for y,c in enumerate(cohorts):
        for x,p in enumerate(phases):
            r=next(r for r in rows if r['cohort']==c and r['phase']==p)
            code={'underground':'U','transition':'T','surface':'S'}[r['actual_context']]
            ax.text(x,y,('Crowd' if matrix[y,x] else 'Static')+'\n'+code,ha='center',va='center',color='white' if matrix[y,x] else 'black',fontsize=9)
    ax.set_xticks(range(5),['Initial','Boundary','After\nboundary','Expiry','Recovery'])
    ax.set_yticks(range(4),['DMRC U → S','DMRC S → U','NMRC outbound','NMRC inbound'])
    ax.tick_params(length=0);ax.set_title('(a) Selected source and configured segment context',loc='left',fontweight='bold',fontsize=10)
    ax.text(0,-.23,'U underground · T transition · S surface\nEach cell: 25 client updates; 20 distinct fixture conditions.',transform=ax.transAxes,fontsize=8)
    ax=axs[0,1]
    subset=[next(r for r in rows if r['cohort']==cohorts[0] and r['phase']==p) for p in phases]
    x=np.arange(5)
    ax.plot(x,[r['baseline_seconds']/60 for r in subset],color='black',linestyle='--',marker='s',label='Stored operator baseline')
    ax.plot(x,[r['actual_journey_seconds']/60 for r in subset],color='black',marker='o',label='Baseline + accepted crowd delay')
    ax.set_xticks(x,['Initial','Boundary','Surface','Expiry','Recovery']);ax.set_ylabel('Planned remaining journey (min)')
    ax.set_title('(b) DMRC underground to surface query sequence',loc='left',fontweight='bold',fontsize=10)
    ax.grid(axis='y',alpha=.25);ax.legend(fontsize=8,frameon=False)
    ax.text(0,-.23,'Origins change by script: Rajiv Chowk → Mandi House → Supreme Court.\nDestination: Yamuna Bank. No train movement is measured.',transform=ax.transAxes,fontsize=8)
    ax=axs[1,0]
    names=['Validated','Historical','Rejected'];vals=[result['processing_outcomes'].get(n.lower(),0) for n in names]
    bars=ax.bar(names,vals,color=['#666666','#bbbbbb','#eeeeee'],edgecolor='black',width=.6)
    for bar,n in zip(bars,vals):ax.text(bar.get_x()+bar.get_width()/2,n+3,str(n),ha='center')
    ax.set_ylim(0,max(vals)*1.22);ax.set_ylabel('Unique reports');ax.set_title('(c) Worker processing outcomes',loc='left',fontweight='bold',fontsize=10)
    ax.text(0,-.18,'400 reports from 100 simulated accounts; 3 duplicate retries excluded.\nRejected reports include missing location evidence and distant GPS.',transform=ax.transAxes,fontsize=8)
    ax=axs[1,1]
    for label,values,style in [('HTTP acknowledgement',[r['elapsed_ms']/1000 for r in result['acks']],'-'),
                             ('Crowd observation to journey update',[r['observed_to_matching_ws_ms']/1000 for r in rows if r['observed_to_matching_ws_ms'] is not None],'--')]:
        values=np.sort(values);ax.step(values,np.arange(1,len(values)+1)/len(values),where='post',color='black',linestyle=style,label=label)
    ax.set_xlabel('Latency (s)');ax.set_ylabel('Empirical cumulative proportion');ax.set_ylim(0,1.04);ax.grid(alpha=.2)
    ax.set_title('(d) Measured loopback delivery latency',loc='left',fontweight='bold',fontsize=10);ax.legend(fontsize=8,frameon=False,loc='lower right')
    ax.text(0,-.23,'HTTP n=400; crowd journey updates n=250. One PostgreSQL run.\nClient observations share four routes; these are not independent field trials.',transform=ax.transAxes,fontsize=8)
    for ext in ['pdf','svg','png']:
        fig.savefig(OUT/f'figure_10_operator_crowd.{ext}',dpi=600 if ext=='png' else None,bbox_inches='tight')
    plt.close(fig)
    caption=('Figure 10. Combined validation using frozen DMRC/NMRC indicative travel times and synthetic crowd reports. '
        '(a) Source selection for four cohorts across five scripted phases (25 clients per cohort; 500 checked journey updates). '
        '(b) Example DMRC route durations as the scripted origin changes; accepted delay is added at boarding once. '
        '(c) Worker outcomes for 400 unique reports. (d) Empirical latency distributions from actual loopback HTTP and journey WebSockets with 100 concurrent clients. '
        'U, T and S denote configured underground, boundary and surface segments. The study evaluates software behavior and delivery; it does not establish field ETA accuracy, individual train tracking, or Prophet/Random Forest performance.')
    (OUT/'figure_10_caption.txt').write_text(caption+'\n',encoding='utf-8')
    print('Created Figure 10 in PDF, SVG and 600 dpi PNG.')


if __name__=='__main__':main()
