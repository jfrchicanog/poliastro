# coding: utf-8
"""Two body problem.

"""

import numpy as np
from numpy.linalg import norm

from astropy import time
from astropy import units as u
u.one = u.dimensionless_unscaled  # astropy #1980

from poliastro.util import transform, check_units

from . import _ast2body

J2000 = time.Time("J2000", scale='utc')


class State(object):
    """Class to represent the position of a body wrt to an attractor.

    """
    def __init__(self, attractor, r, v, epoch):
        """Constructor.

        Parameters
        ----------
        attractor : Body
            Main attractor.
        r, v : array
            Position and velocity vectors.
        epoch : Time
            Epoch.

        """
        self.attractor = attractor
        self.epoch = epoch
        self.r = r
        self.v = v
        self.epoch = epoch
        self._elements = None

    @classmethod
    def from_vectors(cls, attractor, r, v, epoch=J2000):
        """Return `State` object from position and velocity vectors.

        """
        if not check_units((r, v), (u.m, u.m / u.s)):
            raise u.UnitsError("Units must be consistent")

        return cls(attractor, r, v, epoch)

    @classmethod
    def from_elements(cls, attractor, elements, epoch=J2000):
        """Return `State` object from orbital elements.

        """
        # TODO: Desirable?
        #ss_coe.p, ss_coe.ecc, ...
        if len(elements) != 6:
            raise ValueError("Incorrect number of parameters")
        if not check_units(elements, (u.m, u.one, u.rad, u.rad, u.rad, u.rad)):
            raise u.UnitsError("Units must be consistent")

        k = attractor.k.to(u.km ** 3 / u.s ** 2)
        a, ecc, inc, raan, argp, nu = elements
        r, v = coe2rv(k, a, ecc, inc, raan, argp, nu)

        ss = cls(attractor, r, v, epoch)
        ss._elements = elements
        return ss

    @property
    def elements(self):
        """Classical orbital elements.

        """
        if self._elements:
            return self._elements
        else:
            k = self.attractor.k.to(u.km ** 3 / u.s ** 2).value
            r = self.r.to(u.km).value
            v = self.v.to(u.km / u.s).value
            a, ecc, inc, raan, argp, nu = rv2coe(k, r, v)
            self._elements = (a * u.km, ecc * u.one, (inc * u.rad).to(u.deg),
                              (raan * u.rad).to(u.deg),
                              (argp * u.rad).to(u.deg),
                              (nu * u.rad).to(u.deg))
            return self._elements

    def rv(self):
        """Position and velocity vectors.

        """
        return self.r, self.v

    def propagate(self, time_of_flight):
        """Propagate this `State` some `time` and return the result.

        """
        r, v = kepler(self.attractor.k.to(u.km ** 3 / u.s ** 2).value,
                      self.r.to(u.km).value, self.v.to(u.km / u.s).value,
                      time_of_flight.to(u.s).value)
        return self.from_vectors(self.attractor, r * u.km, v * u.km / u.s,
                                 self.epoch + time_of_flight)


def coe2rv(k, a, ecc, inc, raan, argp, nu):
    """Converts from orbital elements to vectors.

    Parameters
    ----------
    k : float
        Standard gravitational parameter (km^3 / s^2).
    a : float
        Semi-major axis (km).
    ecc : float
        Eccentricity.
    inc : float
        Inclination (rad).
    omega : float
        Longitude of ascending node (rad).
    argp : float
        Argument of perigee (rad).
    nu : float
        True anomaly (rad).

    """
    p = a * (1 - ecc ** 2)
    r_pqw = np.array([np.cos(nu) / (1 + ecc * np.cos(nu)),
                      np.sin(nu) / (1 + ecc * np.cos(nu)),
                      0]) * p
    v_pqw = np.array([-np.sin(nu),
                      (ecc + np.cos(nu)),
                      0]) * np.sqrt(k / p)

    r_ijk = transform(r_pqw, -argp, 'z')
    r_ijk = transform(r_ijk, -inc, 'x')
    r_ijk = transform(r_ijk, -raan, 'z')
    v_ijk = transform(v_pqw, -argp, 'z')
    v_ijk = transform(v_ijk, -inc, 'x')
    v_ijk = transform(v_ijk, -raan, 'z')

    return r_ijk, v_ijk


def rv2coe(k, r, v):
    """Converts from vectors to orbital elements.

    Parameters
    ----------
    k : float
        Standard gravitational parameter (km^3 / s^2).
    r : array
        Position vector (km).
    v : array
        Velocity vector (km / s).

    """
    h = np.cross(r, v)
    n = np.cross([0, 0, 1], h) / norm(h)
    e = ((v.dot(v) - k / (norm(r))) * r - r.dot(v) * v) / k
    ecc = norm(e)
    p = h.dot(h) / k
    # TODO: Cannot define a parabola with its semi-major axis
    a = p / (1 - ecc ** 2)

    inc = np.arccos(h[2] / norm(h))
    raan = np.arctan2(n[1], n[0]) % (2 * np.pi)
    argp = np.arctan2(h.dot(np.cross(n, e)) / norm(h), e.dot(n)) % (2 * np.pi)
    nu = np.arctan2(h.dot(np.cross(e, r)) / norm(h), r.dot(e)) % (2 * np.pi)

    return a, ecc, inc, raan, argp, nu


def kepler(k, r0, v0, tof):
    """Propagates orbit.

    This is a wrapper around kepler from ast2body.for.

    Parameters
    ----------
    k : float
        Gravitational constant of main attractor (km^3 / s^2).
    r0 : array
        Initial position (km).
    v0 : array
        Initial velocity (km).
    tof : float
        Time of flight (s).

    Raises
    ------
    RuntimeError
        If the status of the subroutine is not 'ok'.

    """
    r0 = np.asarray(r0).astype(np.float)
    v0 = np.asarray(v0).astype(np.float)
    tof = float(tof)
    assert r0.shape == (3,)
    assert v0.shape == (3,)
    r, v, error = _ast2body.kepler(r0, v0, tof, k)
    error = error.strip().decode('ascii')
    if error != 'ok':
        raise RuntimeError("There was an error: {}".format(error))
    return r, v
