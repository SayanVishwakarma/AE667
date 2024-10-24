#####################################################################################
## THIS PROGRAM USES VALUES OBTAINED FROM THE BLADE TO CALCULATE ROTOR PERFORMANCE ##
#####################################################################################

from __init__ import *

class rotor:

    def __init__(self, rotor_data_file):
            
            self.rotor_data_file = rotor_data_file
            self.read_rotor_data()

    # Reads the rotor data from input JSON file
    def read_rotor_data(self):
          
            with open(self.rotor_data_file) as file:
                raw_data = json.load(file)
            
            self.blade_file_path = raw_data['blade_file_path']
            self.blade = blade.rotorblade(self.blade_file_path)

            self.omega = raw_data['omega']                           # May be changed by the simulator program later, constant for now
            self.number_of_blades = raw_data['number_of_blades']
            self.blade_angle = np.linspace(0, 2*np.pi, self.number_of_blades, endpoint=False) # Angle of each blade from the front of the rotor

# Takes the collective and conditions to get the performance of the rotor
    def get_performance(self, control_msg: message.simMessage):

        input_data = control_msg.get_payload()

        # Evaluate blade performance at every 5 deg of azimuth
        # Azimuth is zero at the tail, increases anti-clockwise when viewed from above
        for phi in np.linspace(0, 2*np.pi, 72, endpoint=False):
             
            # Blade needs number of blades, omega, tangential wind component, climb velocity,
            # atmospheric conditions, pitch angle of the blade, 
            # Calculate the performance of a blade
            blade_conditions = message.simMessage()
            blade_conditions.add_payload({'number_of_blades':self.number_of_blades})
            blade_conditions.add_payload({'omega':self.omega})
            blade_conditions.add_payload({'tangential_vel': input_data['headwind'] * np.sin(phi) + input_data['crosswind'] * np.cos(phi)}) # Tangential wind component
            blade_conditions.add_payload({'climb_vel': input_data['climb_vel']})
            blade_conditions.add_payload({'atmosphere': input_data['atmosphere']})
            blade_conditions.add_payload({'pitch': input_data['collective']}) # Would be calculated from collective and cyclic later

                # Add the performance of this blade to our list
                ###!!!!!! This is being done at a single point. Should be done at every 5 degrees later
            blade_performance = self.blade.get_performance(blade_conditions).get_payload()

        # Calculate the total performance of the rotor
        thrust = self.number_of_blades * blade_performance["thrust"]
        power = self.number_of_blades * blade_performance["power"]
        torque = self.number_of_blades * blade_performance["torque"]

        response = message.simMessage()
        response.add_payload({'thrust': thrust, 'power': power, 'torque': torque})

        return response
    
    # Takes the collectives, cyclics and conditions to get the performance of the rotor
    def get_performance_forward_flight(self, control_msg: message.simMessage):

        input_data = control_msg.get_payload()
        response = message.simMessage()

        # Calculations to help find inflow velocity
        mu = input_data['V_inf'] / (self.omega * self.blade.radius)
        C_T = input_data['thrust'] / (input_data['atmosphere']['density'] \
                                              * np.pi * (self.blade.radius**2-self.blade.root_cutout**2) \
                                              * (self.omega**2) * self.blade.radius**2)
        lambda_i_Glauert = C_T/2/mu
        lambda_G = input_data['V_inf'] / (self.omega * self.blade.radius) + lambda_i_Glauert
        variable_inflow_coefficient = (4/3*mu/lambda_G)/(1.2+mu/lambda_G)

        # TPP angle calculations
        # Lateral TPP angle comes from lateral force and thrust
        alpha_tpp_s = np.arctan(input_data['lateral_force']/input_data['thrust'])
        # Forward alpha_tpp comes from both rotor tilt due to drag and climb velocity
        alpha_tpp_c = np.arctan(input_data['climb_vel']/input_data['V_inf']) \
                    + np.arctan(input_data['total_drag']/input_data['mass']*g)

        # mu has to be greater than 0.2 for this to be valid
        if mu < 0.2:
            response.add_warning({'InflowWarning':'Inflow ratio is less than 0.2. Results may not be accurate.'})
        
        # alpha_tpp has to be small for this to be valid
        if (alpha_tpp_s**2 + alpha_tpp_c**2) > 0.033:
             response.add_warning({'TPPWarning':'TPP angles are too high. Results may not be accurate.'})

        # Evaluate blade performance at every 5 deg of azimuth
        # Azimuth is zero at the tail, increases anti-clockwise when viewed from above
        forces_phi = []
        moments_phi = []
        for phi in np.linspace(0, 2*np.pi, N_INTEGRATION_AZIMUTH, endpoint=False):
             
            # Blade needs number of blades, omega, tangential wind component, climb velocity,
            # atmospheric conditions, pitch angle of the blade, 
            # Calculate the performance of a blade
            blade_conditions = message.simMessage()
            blade_conditions.add_payload({'omega':self.omega})
            blade_conditions.add_payload({'V_inf': input_data['V_inf']}) # Total wind speed
            blade_conditions.add_payload({'phi': phi})
            blade_conditions.add_payload({'atmosphere': input_data['atmosphere']})
            blade_conditions.add_payload({'pitch': input_data['collective'] 
                                                 + input_data['cyclic_c']*np.cos(phi) 
                                                 + input_data['cyclic_s']*np.sin(phi)}) # Would be calculated from collective and cyclic later
            blade_conditions.add_payload({'beta_0': input_data['beta_0']})
            blade_conditions.add_payload({'variable_inflow_coefficient': variable_inflow_coefficient * np.cos(phi)})
            blade_conditions.add_payload({'lambda_i_Glauert': lambda_i_Glauert})
            blade_conditions.add_payload({'alpha_tpp': [alpha_tpp_c, alpha_tpp_s]})

            # Get the results for this phi
            blade_performance = self.blade.get_performance_forward_flight(blade_conditions).get_payload()
            forces_phi.append(blade_performance['forces'])
            moments_phi.append(blade_performance['moments'])

        cycle_avg_force = np.mean(forces_phi, axis=0)
        cycle_avg_moment = np.mean(moments_phi, axis=0)
        
        # Calculate the total performance of the rotor
        thrust = self.number_of_blades * cycle_avg_force[2]  # Thrust is in the z direction
        torque = self.number_of_blades * (-cycle_avg_moment[2]) # Minus sign because torque is in the opposite direction
        power = torque * self.omega

        response.add_payload({'thrust': thrust, 'power': power, 'torque': torque, 'forces': cycle_avg_force, 'moments': cycle_avg_moment})

        return response
    
    def get_performance_forward_flight_2(self, control_msg: message.simMessage):

        input_data = control_msg.get_payload()
        response = message.simMessage()

        # Calculations to help find inflow velocity
        #mu = input_data['V_inf'] / (self.omega * self.blade.radius)
        #C_T = input_data['thrust'] / (input_data['atmosphere']['density'] \
        #                                      * np.pi * (self.blade.radius**2-self.blade.root_cutout**2) \
        #                                      * (self.omega**2) * self.blade.radius**2)
        #lambda_i_Glauert = C_T/2/mu
        #lambda_G = input_data['V_inf'] / (self.omega * self.blade.radius) + lambda_i_Glauert
        #variable_inflow_coefficient = (4/3*mu/lambda_G)/(1.2+mu/lambda_G)

        # mu has to be greater than 0.2 for this to be valid
        #if mu < 0.2:
        #    response.add_warning({'InflowWarning':'Inflow ratio is less than 0.2. Results may not be accurate.'})
        
        # alpha_tpp has to be small for this to be valid
        #if (alpha_tpp_s**2 + alpha_tpp_c**2) > 0.033:
        #     response.add_warning({'TPPWarning':'TPP angles are too high. Results may not be accurate.'})

        # TPP angle calculations
        # Lateral TPP angle comes from lateral force and thrust
        alpha_tpp_s = np.arctan(input_data['lateral_force']/input_data['mass']/g)
        # Forward alpha_tpp comes from both rotor tilt due to drag and climb velocity
        alpha_tpp_c = np.arctan(input_data['total_drag']/input_data['mass']/g) #+ np.arctan(input_data['climb_vel']/input_data['V_inf']) 

        # Evaluate blade performance at every 5 deg of azimuth
        # Azimuth is zero at the tail, increases anti-clockwise when viewed from above
        forces_phi = []
        moments_phi = []
        beta=[]
        for psi in np.linspace(0, 2*np.pi, N_INTEGRATION_AZIMUTH, endpoint=False):
             
            # Blade needs number of blades, omega, tangential wind component, climb velocity,
            # atmospheric conditions, pitch angle of the blade, 
            # Calculate the performance of a blade
            blade_conditions = message.simMessage()
            blade_conditions.add_payload({'omega':self.omega})
            blade_conditions.add_payload({'V_inf': input_data['V_inf']}) # Total wind speed
            blade_conditions.add_payload({'psi': psi})
            blade_conditions.add_payload({'atmosphere': input_data['atmosphere']})
            blade_conditions.add_payload({'pitch': input_data['collective'] 
                                                 + input_data['cyclic_c']*np.cos(psi) 
                                                 + input_data['cyclic_s']*np.sin(psi)}) # Would be calculated from collective and cyclic later
            #blade_conditions.add_payload({'beta_0': input_data['beta_0']})
            #blade_conditions.add_payload({'variable_inflow_coefficient': variable_inflow_coefficient * np.cos(phi)})
            #blade_conditions.add_payload({'lambda_i_Glauert': lambda_i_Glauert})
            blade_conditions.add_payload({'alpha_tpp': [alpha_tpp_c, alpha_tpp_s]})

            # Get the results for this phi
            blade_performance = self.blade.get_performance_forward_flight_2(blade_conditions).get_payload()
            forces_phi.append(blade_performance['forces'])
            moments_phi.append(blade_performance['moments'])
            beta.append(blade_performance['beta'])

        cycle_avg_force = np.mean(forces_phi, axis=0)
        cycle_avg_moment = np.mean(moments_phi, axis=0)
        
        # Calculate the total performance of the rotor
        thrust = self.number_of_blades * cycle_avg_force[2]  # Thrust is in the z direction
        torque = self.number_of_blades * (-cycle_avg_moment[2]) # Minus sign because torque is in the opposite direction
        power = torque * self.omega

        response.add_payload({'thrust': thrust, 'power': power, 'torque': torque, 'forces': cycle_avg_force, 'moments': cycle_avg_moment,
                              'Force_y':thrust*np.cos(alpha_tpp_c),'Force_z':thrust*np.sin(alpha_tpp_c),'beta':beta})

        return response
    
    def get_performance_forward_flight_3(self, control_msg: message.simMessage):

        input_data = control_msg.get_payload()
        response = message.simMessage()
        alpha_tpp_s = np.arctan(input_data['lateral_force']/input_data['mass']/g)
        # Forward alpha_tpp comes from both rotor tilt due to drag and climb velocity
        alpha_tpp_c = np.arctan(input_data['total_drag']/input_data['mass']/g) #+ np.arctan(input_data['climb_vel']/input_data['V_inf']) 

        # Evaluate blade performance at every 5 deg of azimuth
        # Azimuth is zero at the tail, increases anti-clockwise when viewed from above
        forces_phi = []
        moments_phi = []
        beta=[]
        psi=np.linspace(0,pi,72)
        blade_conditions = message.simMessage()
        blade_conditions.add_payload({'omega':self.omega})
        blade_conditions.add_payload({'V_inf': input_data['V_inf']}) # Total wind speed
        blade_conditions.add_payload({'psi': psi})
        blade_conditions.add_payload({'atmosphere': input_data['atmosphere']})
        blade_conditions.add_payload({'pitch': input_data['collective'] 
                                                 + input_data['cyclic_c']*np.cos(psi) 
                                                 + input_data['cyclic_s']*np.sin(psi)})
        blade_conditions.add_payload({'alpha_tpp': [alpha_tpp_c, alpha_tpp_s]})
        blade_performance = self.blade.get_performance_forward_flight_2(blade_conditions).get_payload()
        forces_phi.append(blade_performance['forces'])
        moments_phi.append(blade_performance['moments'])
        beta.append(blade_performance['beta'])

        cycle_avg_force = np.mean(forces_phi, axis=0)
        cycle_avg_moment = np.mean(moments_phi, axis=0)
        
        # Calculate the total performance of the rotor
        thrust = self.number_of_blades * cycle_avg_force[2]  # Thrust is in the z direction
        torque = self.number_of_blades * (-cycle_avg_moment[2]) # Minus sign because torque is in the opposite direction
        power = np.abs(torque * self.omega)

        response.add_payload({'thrust': thrust, 'power': power, 'torque': torque, 'forces': cycle_avg_force, 'moments': cycle_avg_moment,
                              'Force_y':thrust*np.cos(alpha_tpp_c),'Force_z':thrust*np.sin(alpha_tpp_c),'beta':beta})

        return response
    
    # Takes required thrust and conditions to get the collective required, power required and torque.
    def set_thrust(self, conditions: message.simMessage):

        response = message.simMessage()

        conditions = conditions.get_payload()
        collective_lower = 0
        collective_upper = self.blade.airfoil.alphacrit
        collective = (collective_lower + collective_upper)/2
        rotor_performance = None

        # Bisection method to find the collective required to maintain hover
        for i in range(CONTROLS_CONVERGENCE_ITERATIONS):

            rotor_performance = self.get_performance(message.simMessage(payload = {'collective': collective,**conditions,'atmosphere':conditions['atmosphere']})).get_payload()
            if rotor_performance['thrust'] > conditions['desired_thrust']:
                collective_upper = collective
                collective = (collective + collective_lower)/2
            else:
                collective_lower = collective
                collective = (collective + collective_upper)/2

            if abs((rotor_performance['thrust']-conditions['desired_thrust'])/conditions['mass']) < ACCELERATION_TOLERANCE: # Convergence criteria
                break

            # This will only run if the collective pitch doesn't converge or the rotor can't produce enough thrust
            if i == CONTROLS_CONVERGENCE_ITERATIONS - 1:
                response.add_error({'ConvergenceError':'Thrust convergence could not be achieved. Try increasing CONTROLS_CONVERGENCE_ITERATIONS.'})
        
        response.add_payload(rotor_performance)
        response.add_payload({'collective':collective})

        return response
    
     # Takes required thrust, alpha_tpp and conditions to get the collective and cyclic required, power required and torque in forward flight
    def set_collectives_forward_flight(self, conditions: message.simMessage):

        response = message.simMessage()

        conditions = conditions.get_payload()
        collective_lower = 0
        collective_upper = self.blade.airfoil.alphacrit
        collective = (collective_lower + collective_upper)/2
        collective_1c = (collective_lower + collective_upper)/2
        rotor_performance = None
        set_collective=collective
        set_collective_1c=collective_1c
        print('Starting forward flight trim iterations')
        for j in range(CONTROLS_CONVERGENCE_ITERATIONS):
        # Bisection method to find the collective required to maintain hover
            collective_lower = 0
            collective_upper = self.blade.airfoil.alphacrit
            collective = set_collective
            collective_1c = set_collective_1c
            for i in range(CONTROLS_CONVERGENCE_ITERATIONS):
                b = message.simMessage(payload={'mass':conditions['mass'],'total_drag':conditions['total_drag'],'lateral_force':0,'atmosphere':conditions['atmosphere'],
                                                             'cyclic_c':set_collective_1c,'cyclic_s':0,'collective':collective,
                                                                "V_inf":conditions['V_inf'],'climb_vel':conditions['climb_vel'],'headwind':0,'crosswind':0})
                rotor_performance = self.get_performance_forward_flight_2(b).get_payload()
                desired_thrust=((conditions['mass']*g)**2+conditions['total_drag']**2)**0.5
                #print('Collective',set_collective)
                if abs((rotor_performance['thrust']-desired_thrust)/conditions['mass']) < ACCELERATION_TOLERANCE: # Convergence criteria
                    set_collective=collective
                    break
                if rotor_performance['thrust'] > desired_thrust:
                    collective_upper = collective
                    collective = (collective + collective_lower)/2
                else:
                    collective_lower = collective
                    collective = (collective + collective_upper)/2

                #if abs((rotor_performance['thrust']-conditions['desired_thrust'])/conditions['mass']) < ACCELERATION_TOLERANCE: # Convergence criteria
                #    break

            # This will only run if the collective pitch doesn't converge or the rotor can't produce enough thrust
                if i == CONTROLS_CONVERGENCE_ITERATIONS - 1:
                    response.add_error({'ConvergenceError':'Thrust convergence could not be achieved. Try increasing CONTROLS_CONVERGENCE_ITERATIONS.'})

            collective_lower = 0
            collective_upper = self.blade.airfoil.alphacrit
            collective = set_collective
            collective_1c = set_collective_1c
            for i in range(CONTROLS_CONVERGENCE_ITERATIONS):
                b = message.simMessage(payload={'mass':conditions['mass'],'total_drag':conditions['total_drag'],'lateral_force':0,'atmosphere':conditions['atmosphere'],
                                                                'cyclic_c':collective_1c,'cyclic_s':0,'collective':set_collective,
                                                                "V_inf":conditions['V_inf'],'climb_vel':conditions['climb_vel'],'headwind':0,'crosswind':0})
                rotor_performance = self.get_performance_forward_flight_2(b).get_payload()
                alpha_tpp=conditions['total_drag']/conditions['mass']/g
                beta_1c=rotor_performance['beta'][0]-rotor_performance['beta'][36]
                #print('Cyclic_1c',set_collective_1c)
                if abs(beta_1c-alpha_tpp) < BETA_TOLERANCE: # Convergence criteria
                    set_collective_1c=collective_1c
                    break
                if beta_1c > alpha_tpp:
                    collective_upper = collective_1c
                    collective_1c = (collective_1c + collective_lower)/2
                else:
                    collective_lower = collective_1c
                    collective_1c = (collective_1c + collective_upper)/2
            # This will only run if the collective pitch doesn't converge or the rotor can't produce enough thrust
                if i == CONTROLS_CONVERGENCE_ITERATIONS - 1:
                    response.add_error({'ConvergenceError':'Thrust convergence could not be achieved. Try increasing CONTROLS_CONVERGENCE_ITERATIONS.'})
            t=rotor_performance['thrust']
            w=conditions['mass']*g
            print(f'After :{j+1} iterations \n Thrust={t}, Required thrust={w} \n Beta_1c={beta_1c} , alpha_tpp:{alpha_tpp}')
            print(f' Collective={set_collective}, Cyclic_1c={set_collective_1c}')
        response.add_payload(rotor_performance)
        response.add_payload({'collective':collective,'cyclic_1c':set_collective_1c})

        return response
    
