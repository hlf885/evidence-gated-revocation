"""Study D: watchdog observation errors with optional persistence (Markov), plus the v11 belief rule.

Per goal, an error at refresh k depends on whether the same goal was in error at refresh k-1:
    P(error_k | error_{k-1}) = s,   P(error_k | no error_{k-1}) = p0 = r(1-s)/(1-r)
so the stationary error rate among eligible observations is r. 'independent' sets s = r (p0 = r),
which reproduces the v10 WatchdogNoise exactly; 'persistent' sets s = PERSIST (mean error run 1/(1-s)).
A goal that is not eligible at refresh k (its true state cannot be flipped by this error type) resets.
Common random numbers: u = uniform(protocol_id, seed, noise_type, k, goal) as in v10.
"""
from pathlib import Path
import copy, sys
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from belief_rules import make_memory, uniform, BELIEF_PARAMS, belief_step   # noqa: E402,F401
from contracts import ContractError   # noqa: E402

PERSIST = 0.8
CORRELATIONS = ('none', 'independent', 'persistent')


def stay_prob(rate, correlation):
    return rate if correlation == 'independent' else PERSIST


def error_now(u, rate, correlation, prev_error):
    s = stay_prob(rate, correlation); p0 = rate*(1-s)/(1-rate)
    return u < (s if prev_error else p0)


def eligible(noise_type, true_state):
    return (noise_type == 'false_invalid' and true_state == 'CONSISTENT') or \
           (noise_type == 'false_consistent' and true_state in ('INVALID', 'UNKNOWN'))


class CorrelatedWatchdogNoise:
    def __init__(self, protocol_id, seed, noise_type, rate, correlation):
        ok = (noise_type == 'none' and rate == 0 and correlation == 'none') or \
             (noise_type in ('false_invalid', 'false_consistent') and 0 < rate < 1 and correlation in ('independent', 'persistent'))
        if not ok: raise ContractError('invalid noise specification')
        self.protocol_id = protocol_id; self.seed = seed; self.noise_type = noise_type; self.rate = rate
        self.correlation = correlation; self.refresh_index = 0; self.flip_count = 0; self.prev = {}

    def apply(self, snapshot):
        k = self.refresh_index; self.refresh_index += 1
        noisy = copy.deepcopy(snapshot); flips = []
        if self.noise_type == 'none':
            return noisy, flips
        for row in noisy.get('goals', []):
            g = row.get('goalId'); true_state = row.get('state')
            if not eligible(self.noise_type, true_state):
                self.prev[g] = False; continue
            u = uniform(self.protocol_id, self.seed, self.noise_type, k, g)
            err = error_now(u, self.rate, self.correlation, self.prev.get(g, False)); self.prev[g] = err
            if err:
                row['state'] = 'INVALID' if self.noise_type == 'false_invalid' else 'CONSISTENT'
                row['reason'] = 'synthetic_observation_error'
                flips.append({'goalId': g, 'true_state': true_state, 'reported_state': row['state'], 'refresh_index': k, 'u': u})
        self.flip_count += len(flips)
        return noisy, flips


def make_noise(protocol_id, seed, unit):
    return CorrelatedWatchdogNoise(protocol_id, seed, unit['noise_type'], unit['noise_rate'], unit['noise_correlation'])
